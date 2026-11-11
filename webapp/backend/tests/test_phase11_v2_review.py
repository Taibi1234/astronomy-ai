"""Review-stage tests: fail-closed fixes in phase11_v2 and the dedicated v2 CLI.

Synthetic fixtures only. Two tests read the frozen protocol and manifests read-only and
skip when those files are absent, so the module runs in a clean checkout.
"""

from __future__ import annotations

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
from research import phase11  # noqa: E402
from research import phase11_v2 as v2  # noqa: E402
from research import run_phase11 as legacy_runner  # noqa: E402
from research import run_phase11_v2 as cli  # noqa: E402

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"
PROTOCOL_PATH = MANIFEST_DIR / v2.AUTHORIZED_PROTOCOL_NAME
needs_frozen_inputs = pytest.mark.skipif(
    not PROTOCOL_PATH.is_file() or not (MANIFEST_DIR / "windows_primary.json").is_file(),
    reason="frozen protocol/manifests are not present",
)


# --- review fixes: fail-closed error types ---------------------------------


def test_git_missing_working_directory_fails_closed(tmp_path):
    with pytest.raises(v2.GateError, match="git is unavailable"):
        v2._git(tmp_path / "does-not-exist", "rev-parse", "HEAD")


def test_source_manifest_hash_rejects_missing_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(v2.GateError, match="does not exist"):
        v2.source_manifest_hash([repo / "missing.py"], repo)


def test_threshold_rejects_non_finite_floor():
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(v2.GateError, match="floor must be finite"):
            v2.choose_threshold_v21(np.arange(40), scope="unit", floor=bad)


def test_comparison_rejects_any_caller_supplied_mmd():
    frame = _paired_frame()
    for bad in (0.0, -0.05, 0.1, 1.0):
        with pytest.raises(v2.GateError, match="caller-supplied overrides are refused"):
            v2.paired_comparison(frame, mmd=bad, resamples=50)


def test_comparison_rejects_too_few_resamples():
    with pytest.raises(v2.GateError, match="resamples must be at least 2"):
        v2.paired_comparison(_paired_frame(), resamples=1)


def test_combine_rejects_unknown_status():
    with pytest.raises(v2.GateError, match="unrecognised comparison status"):
        v2.combine_confirmatory({"observed": {"status": "maybe_superior"}})


def test_load_fitted_requires_model_sha256(tmp_path):
    (tmp_path / "model.pkl").write_bytes(b"x")
    payload = {
        "schema_version": 2,
        "protocol_sha256": "abc",
        "model_file": "model.pkl",
        "provenance": {},
    }
    phase11.write_json_with_sidecar(tmp_path / "fitted.json", payload)
    with pytest.raises(v2.GateError, match="no model_sha256"):
        v2.load_fitted_v21(tmp_path, "abc")


@needs_frozen_inputs
def test_protocol_requires_frozen_inputs_mapping(tmp_path):
    payload = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    payload["frozen_inputs"]["files"] = ["not", "a", "mapping"]
    copy = tmp_path / "protocol_v2_3.json"
    phase11.write_json_with_sidecar(copy, payload)
    with pytest.raises(v2.GateError, match="frozen_inputs.files"):
        v2.load_protocol_v21(copy, expected_sha256=v2.sha256_file(copy))


# --- v2 CLI: refusal paths --------------------------------------------------


def test_only_preflight_mode_is_enabled():
    assert cli.ENABLED_MODES == ("preflight",)
    assert "smoke" in cli.KNOWN_MODES
    assert "full" in cli.KNOWN_MODES
    assert "sensitivity" in cli.KNOWN_MODES


@pytest.mark.parametrize("mode", ["smoke", "full", "sensitivity"])
def test_cli_refuses_every_campaign_mode(mode, tmp_path, capsys):
    code = cli.main(["--mode", mode, "--out", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert code == cli.EXIT_CLI_REFUSED
    assert "not enabled" in captured.err
    assert "no fallback to the v1 runner" in captured.err


def test_cli_requires_an_output_directory(capsys):
    code = cli.main(["--mode", "preflight"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_CLI_REFUSED
    assert "--out" in captured.err


def test_cli_returns_gate_exit_code_on_refusal(tmp_path, monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise v2.GateError("synthetic refusal")

    monkeypatch.setattr(cli, "preflight", refuse)
    code = cli.main(["--out", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert code == cli.EXIT_GATE_REFUSED
    assert "preflight refused: synthetic refusal" in captured.err


def test_cli_prints_json_and_exits_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "preflight", lambda *a, **k: {"protocol_version": "phase11b-protocol-v2.3-proposal"}
    )
    code = cli.main(["--out", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert code == cli.EXIT_OK
    assert json.loads(captured.out)["protocol_version"] == "phase11b-protocol-v2.3-proposal"


def test_cli_has_no_v1_fallback_or_execution_path():
    source = Path(cli.__file__).read_text(encoding="utf-8")
    for token in ("run_campaign", "evaluate_test", "run_smoke", "from . import run_phase11"):
        assert token not in source, f"CLI must not reach the campaign path: {token}"


@needs_frozen_inputs
def test_cli_pin_rejects_a_protocol_that_is_not_authorized(tmp_path, monkeypatch):
    monkeypatch.setattr(v2, "AUTHORIZED_PROTOCOL_SHA256", "0" * 64)
    with pytest.raises(v2.GateError, match="not the authorized protocol"):
        cli.preflight(MANIFEST_DIR, tmp_path / "out", gen.project_root())


@needs_frozen_inputs
def test_cli_preflight_passes_on_frozen_inputs_and_writes_nothing(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr(
        v2,
        "git_provenance",
        lambda root: {"commit": "abc123", "branch": "main", "dirty": False, "dirty_paths": []},
    )
    result = cli.preflight(MANIFEST_DIR, out_dir, gen.project_root())
    assert result["mode"] == "preflight"
    assert result["protocol_version"] == "phase11b-protocol-v2.3-proposal"
    assert result["protocol_hash"] == v2.AUTHORIZED_PROTOCOL_SHA256
    assert result["reads_test"] is False
    assert result["writes"] == []
    assert result["campaign_authorized"] is False
    assert sorted(result["manifests"]) == sorted(v2.MANIFEST_NAMES)
    assert list(out_dir.iterdir()) == []
    assert result["provenance"]["source_manifest_sha256"] != ""


def test_cli_main_is_not_reachable_through_the_v1_module():
    """The v1 runner must not expose a v2 entry point."""
    source = Path(legacy_runner.__file__).read_text(encoding="utf-8")
    assert "phase11_v2" not in source


# --- fixture ----------------------------------------------------------------


def _paired_frame() -> pd.DataFrame:
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
