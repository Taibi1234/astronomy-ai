"""Execution-safety closure tests: one-shot access state machine and legacy gates.

All fixtures are temporary. No campaign runs, no model is fitted on real data, no sealed
trial is read, and no marker is created in a campaign directory.
"""

from __future__ import annotations

import json
import pickle
import subprocess
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

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"


# --- helpers ----------------------------------------------------------------


class _StubModel:
    def predict_proba(self, matrix):
        rows = len(matrix)
        return np.column_stack([np.full(rows, 0.9), np.full(rows, 0.1)])


class _FrameTouched(Exception):
    """Raised by the spy when evaluation touches the trial frame."""


class _SpyFrame:
    """Fails the test if evaluation touches trials before the claim exists."""

    def __init__(self, marker: Path):
        self.marker = marker
        self.touched = False

    def __getitem__(self, item):  # noqa: ARG002
        self.touched = True
        if not self.marker.is_file():
            raise AssertionError("trial frame touched before the access claim")
        raise _FrameTouched("frame access reached with the claim in place")


def _stub_evaluate_preconditions(monkeypatch, out_dir: Path) -> None:
    (out_dir / "model.pkl").write_bytes(pickle.dumps(_StubModel()))
    monkeypatch.setattr(
        phase11, "load_frozen_json", lambda *a, **k: ({"phase": "11b"}, "protocol-hash")
    )
    monkeypatch.setattr(phase11, "assert_protocol_manifests", lambda *a, **k: None)
    monkeypatch.setattr(
        phase11,
        "load_fitted",
        lambda *a, **k: {
            "schema_version": 1,
            "threshold": {"threshold": 0.5, "scope": "unit"},
            "features": ["snr"],
            "imputation_medians": [0.0],
            "model_file": "model.pkl",
            "_sha256": "fitted-hash",
        },
    )


def _subprocess_claim(out_dir: Path, *, marker: str) -> subprocess.Popen:
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(BACKEND_DIR)!r});"
        "from pathlib import Path;"
        "from research import test_access as ta;"
        f"getattr(ta, {marker!r})(Path({str(out_dir)!r}), {{'worker': True}})"
    )
    return subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


# --- state machine: cross-process atomicity ---------------------------------


def test_four_processes_race_and_exactly_one_claims(tmp_path):
    processes = [_subprocess_claim(tmp_path, marker="claim_access") for _ in range(4)]
    codes = [process.wait(timeout=120) for process in processes]
    for process in processes:
        process.stdout.close()
        process.stderr.close()

    assert codes.count(0) == 1, f"exactly one claim must succeed, got {codes}"
    assert codes.count(1) == 3, f"the losers must exit non-zero, got {codes}"
    assert test_access.marker_state(tmp_path, test_access.MARKER_ACCESS) == "started"
    assert len([p for p in tmp_path.iterdir() if p.suffix == ".json"]) == 1


def test_sequential_second_process_is_refused(tmp_path):
    first = _subprocess_claim(tmp_path, marker="claim_access")
    assert first.wait(timeout=120) == 0
    first.stdout.close()
    first.stderr.close()

    second = _subprocess_claim(tmp_path, marker="claim_access")
    assert second.wait(timeout=120) == 1
    second.stdout.close()
    second.stderr.close()
    assert test_access.marker_state(tmp_path, test_access.MARKER_ACCESS) == "started"


def test_four_processes_race_for_generation_and_exactly_one_claims(tmp_path):
    processes = [_subprocess_claim(tmp_path, marker="claim_generation") for _ in range(4)]
    codes = [process.wait(timeout=120) for process in processes]
    for process in processes:
        process.stdout.close()
        process.stderr.close()

    assert codes.count(0) == 1, f"exactly one generation claim must succeed, got {codes}"
    assert test_access.marker_state(tmp_path, test_access.MARKER_GENERATION) == "started"


# --- state machine: interruption, partial and invalid state -----------------


def test_interrupted_claim_is_terminal(tmp_path):
    test_access.claim_access(tmp_path, {"worker": 1})
    with pytest.raises(test_access.GateError, match="one-shot"):
        test_access.claim_access(tmp_path, {"worker": 2})
    with pytest.raises(test_access.GateError, match="never reset"):
        test_access.assert_no_markers(tmp_path)


def test_partial_and_malformed_markers_block_execution(tmp_path):
    for payload in ("", "{not json", '{"status": "half-done"}'):
        marker = tmp_path / test_access.MARKER_ACCESS
        marker.write_text(payload, encoding="utf-8")
        assert test_access.marker_state(tmp_path, test_access.MARKER_ACCESS) == "invalid"
        with pytest.raises(test_access.GateError):
            test_access.claim_access(tmp_path, {})
        marker.unlink()


def test_claim_access_requires_a_completed_generation_claim(tmp_path):
    test_access.claim_generation(tmp_path, {})
    with pytest.raises(test_access.GateError, match="requires a completed generation"):
        test_access.claim_access(tmp_path, {})

    test_access.complete_marker(tmp_path, test_access.MARKER_GENERATION)
    test_access.claim_access(tmp_path, {})
    assert test_access.marker_state(tmp_path, test_access.MARKER_ACCESS) == "started"


def test_generation_is_refused_after_access_was_claimed(tmp_path):
    test_access.claim_access(tmp_path, {})
    with pytest.raises(test_access.GateError, match="refused after any access claim"):
        test_access.claim_generation(tmp_path, {})


def test_no_reset_or_delete_helper_exists():
    source = Path(test_access.__file__).read_text(encoding="utf-8")
    for token in ("unlink", "os.remove", "shutil.rmtree", "def reset", "def clear"):
        assert token not in source, f"state machine must not offer {token}"


# --- legacy v1 evaluator: fail closed --------------------------------------


def test_legacy_evaluate_claims_before_touching_trials(tmp_path, monkeypatch):
    _stub_evaluate_preconditions(monkeypatch, tmp_path)
    spy = _SpyFrame(tmp_path / test_access.MARKER_ACCESS)
    with pytest.raises(_FrameTouched):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=spy,
            manifest_dir=MANIFEST_DIR,
        )
    assert spy.touched is True
    assert test_access.marker_state(tmp_path, test_access.MARKER_ACCESS) == "started"


def test_legacy_evaluate_refuses_a_second_read(tmp_path, monkeypatch):
    _stub_evaluate_preconditions(monkeypatch, tmp_path)
    test_access.claim_access(tmp_path, {"prior": True})
    spy = _SpyFrame(tmp_path / test_access.MARKER_ACCESS)
    with pytest.raises(phase11.GateError, match="one-shot"):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=spy,
            manifest_dir=MANIFEST_DIR,
        )
    assert spy.touched is False, "a refused attempt must not touch the trial frame"


def test_legacy_evaluate_refuses_an_invalid_or_partial_marker(tmp_path, monkeypatch):
    _stub_evaluate_preconditions(monkeypatch, tmp_path)
    (tmp_path / test_access.MARKER_ACCESS).write_text("", encoding="utf-8")
    spy = _SpyFrame(tmp_path / test_access.MARKER_ACCESS)
    with pytest.raises(phase11.GateError):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=spy,
            manifest_dir=MANIFEST_DIR,
        )
    assert spy.touched is False


def test_legacy_evaluate_refuses_a_v2_fitted_state(tmp_path, monkeypatch):
    _stub_evaluate_preconditions(monkeypatch, tmp_path)
    monkeypatch.setattr(
        phase11,
        "load_fitted",
        lambda *a, **k: {"schema_version": 2, "threshold": {}, "model_file": "model.pkl"},
    )
    with pytest.raises(phase11.GateError, match="v2 fitted state"):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=_SpyFrame(tmp_path / test_access.MARKER_ACCESS),
            manifest_dir=MANIFEST_DIR,
        )
    assert test_access.marker_state(tmp_path, test_access.MARKER_ACCESS) is None


def test_legacy_evaluate_failure_leaves_a_terminal_marker(tmp_path, monkeypatch):
    _stub_evaluate_preconditions(monkeypatch, tmp_path)

    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic metrics failure")

    monkeypatch.setattr(phase11, "detection_metrics", boom)
    frame = pd.DataFrame(
        {
            "split": ["test"],
            "injected": [1],
            "snr": [1.0],
            "quarter": ["Q09"],
            "requested_depth_ppm": [100.0],
        }
    )
    with pytest.raises(RuntimeError, match="synthetic metrics failure"):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=frame,
            manifest_dir=MANIFEST_DIR,
        )
    ledger = json.loads((tmp_path / test_access.MARKER_ACCESS).read_text(encoding="utf-8"))
    assert ledger["status"] == "started"
    with pytest.raises(phase11.GateError, match="one-shot"):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=frame,
            manifest_dir=MANIFEST_DIR,
        )


# --- legacy v1 campaign: test-trial generation -----------------------------


def test_generation_claim_precedes_any_trial_planning(tmp_path, monkeypatch):
    marker = tmp_path / test_access.MARKER_GENERATION

    def spy_plan(*_args, **_kwargs):
        assert marker.is_file(), "test trials planned before the generation claim"
        raise _FrameTouched("planning reached with the claim in place")

    monkeypatch.setattr(phase11, "assert_test_generation_allowed", lambda *_a, **_k: None)
    monkeypatch.setattr(phase11, "plan_trials", spy_plan)
    with pytest.raises(_FrameTouched):
        phase11.run_campaign(
            manifest_dir=MANIFEST_DIR, out_dir=tmp_path, window_days=5.0, split_group="test"
        )
    assert test_access.marker_state(tmp_path, test_access.MARKER_GENERATION) == "started"
    assert not (tmp_path / "trials_test.csv").exists()


def test_duplicate_generation_attempt_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(phase11, "assert_test_generation_allowed", lambda *_a, **_k: None)
    monkeypatch.setattr(phase11, "plan_trials", lambda *_a, **_k: _raise(_FrameTouched("first")))
    with pytest.raises(_FrameTouched):
        phase11.run_campaign(
            manifest_dir=MANIFEST_DIR, out_dir=tmp_path, window_days=5.0, split_group="test"
        )
    with pytest.raises(phase11.GateError, match="refused after any access claim"):
        phase11.run_campaign(
            manifest_dir=MANIFEST_DIR, out_dir=tmp_path, window_days=5.0, split_group="test"
        )


def test_fit_split_generation_is_unaffected(tmp_path, monkeypatch):
    monkeypatch.setattr(phase11, "plan_trials", lambda *_a, **_k: _raise(_FrameTouched("fit")))
    with pytest.raises(_FrameTouched):
        phase11.run_campaign(
            manifest_dir=MANIFEST_DIR, out_dir=tmp_path, window_days=5.0, split_group="fit"
        )
    assert test_access.marker_state(tmp_path, test_access.MARKER_GENERATION) is None
    assert test_access.marker_state(tmp_path, test_access.MARKER_ACCESS) is None


def _raise(exc):
    raise exc


# --- copied protected layouts through lower-level writers -------------------


def test_writers_refuse_a_copied_smoke_layout(tmp_path, monkeypatch):
    copied = tmp_path / "copy" / "phase11_generalization" / "smoke"
    copied.mkdir(parents=True)
    (copied / "fitted.json").write_text('{"status": "completed"}', encoding="utf-8")
    (copied / "model.pkl").write_bytes(b"x")

    monkeypatch.setattr(gen, "build_manifests", lambda root=None: {"a.json": {}})
    with pytest.raises(safeguards.SafeguardError, match="campaign state"):
        gen.write_manifests(copied)

    monkeypatch.setattr(phase11, "build_stage0", lambda manifest_dir: {"protocol.json": {}})
    with pytest.raises(safeguards.SafeguardError, match="campaign state"):
        phase11.write_stage0(copied, tmp_path)
    assert sorted(p.name for p in copied.iterdir()) == ["fitted.json", "model.pkl"]


def test_writers_refuse_a_copied_layout_holding_an_access_marker(tmp_path, monkeypatch):
    copied = tmp_path / "copy" / "phase11_generalization"
    copied.mkdir(parents=True)
    (copied / "test_access.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(phase11, "build_stage0", lambda manifest_dir: {"protocol.json": {}})
    with pytest.raises(safeguards.SafeguardError, match="campaign state"):
        phase11.write_stage0(copied, tmp_path)
    assert not (copied / "protocol.json").exists()


def test_writers_remain_repeatable_in_a_fresh_directory(tmp_path, monkeypatch):
    target = tmp_path / "fresh"
    monkeypatch.setattr(phase11, "build_stage0", lambda manifest_dir: {"protocol.json": {"a": 1}})
    phase11.write_stage0(target, tmp_path)
    phase11.write_stage0(target, tmp_path)
    assert (target / "protocol.json").is_file()
    assert (target / "protocol.sha256").is_file()
    assert safeguards.assert_no_campaign_state(target, purpose="unit") == target.resolve()
