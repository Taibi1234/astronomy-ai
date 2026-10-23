"""Stage A runner tests: preflight, readiness gates, isolation, integrity, state machine.

Synthetic fixtures only. No scientific input is read, no model is fitted, no campaign runs,
and no marker is created outside ``tmp_path``.
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import generalization as gen  # noqa: E402
from research import phase11_runner as runner  # noqa: E402
from research import phase11_v2 as v2  # noqa: E402
from research import test_access  # noqa: E402

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"
needs_frozen = pytest.mark.skipif(
    not (MANIFEST_DIR / v2.AUTHORIZED_PROTOCOL_NAME).is_file(),
    reason="frozen protocol is not present",
)


def _clean_git(monkeypatch, *, dirty: bool = False) -> None:
    monkeypatch.setattr(
        v2,
        "git_provenance",
        lambda root: {
            "commit": "abc123",
            "branch": "main",
            "dirty": dirty,
            "dirty_paths": [" M research/phase11_runner.py"] if dirty else [],
        },
    )


def _subprocess_claim(out_dir: Path) -> subprocess.Popen:
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(BACKEND_DIR)!r});"
        "from pathlib import Path;"
        "from research import test_access as ta;"
        f"ta.claim_access(Path({str(out_dir)!r}), {{'worker': True}})"
    )
    return subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


# --- preflight --------------------------------------------------------------


@needs_frozen
def test_preflight_succeeds_but_reports_the_readiness_blockers(tmp_path, monkeypatch):
    _clean_git(monkeypatch)
    out = tmp_path / "out"
    out.mkdir()
    result = runner.preflight(MANIFEST_DIR, out, gen.project_root())

    assert result["stage"] == "A"
    assert result["mode"] == "preflight"
    assert result["protocol_version"] == v2.AUTHORIZED_PROTOCOL_VERSION
    assert result["protocol_hash"] == v2.AUTHORIZED_PROTOCOL_SHA256
    assert result["execution_authorized"] is False
    blockers = " | ".join(result["execution_blockers"])
    assert "campaign_ready" in blockers
    assert "execution_ready" in blockers
    assert "not authorized" in blockers
    assert result["reads_test"] is False
    assert result["writes"] == []
    assert list(out.iterdir()) == [], "preflight must not write"


def test_preflight_refuses_protected_and_frozen_tree_outputs(tmp_path, monkeypatch):
    _clean_git(monkeypatch)
    for target in (MANIFEST_DIR, MANIFEST_DIR / "stageA_out", MANIFEST_DIR / "smoke"):
        with pytest.raises(runner.OutputIsolationError):
            runner.preflight(MANIFEST_DIR, target, gen.project_root())


def test_preflight_refuses_v1_stage0_and_campaign_state_outputs(tmp_path, monkeypatch):
    _clean_git(monkeypatch)
    v1_like = tmp_path / "v1like"
    v1_like.mkdir()
    (v1_like / "protocol.json").write_text("{}", encoding="utf-8")
    with pytest.raises(runner.OutputIsolationError, match="v1 stage-0"):
        runner.preflight(MANIFEST_DIR, v1_like, gen.project_root())

    campaign_like = tmp_path / "campaign_like"
    campaign_like.mkdir()
    (campaign_like / "fitted.json").write_text("{}", encoding="utf-8")
    with pytest.raises(runner.OutputIsolationError, match="campaign state"):
        runner.preflight(MANIFEST_DIR, campaign_like, gen.project_root())


@needs_frozen
def test_preflight_fails_closed_on_pin_mismatch(tmp_path, monkeypatch):
    _clean_git(monkeypatch)
    monkeypatch.setattr(v2, "AUTHORIZED_PROTOCOL_SHA256", "0" * 64)
    with pytest.raises(v2.GateError, match="not the authorized protocol"):
        runner.preflight(MANIFEST_DIR, tmp_path / "out", gen.project_root())


@needs_frozen
def test_preflight_fails_closed_on_dirty_tree(tmp_path, monkeypatch):
    _clean_git(monkeypatch, dirty=True)
    with pytest.raises(v2.GateError, match="clean tracked tree"):
        runner.preflight(MANIFEST_DIR, tmp_path / "out", gen.project_root())


@needs_frozen
def test_preflight_fails_closed_on_a_missing_source_entry(tmp_path, monkeypatch):
    _clean_git(monkeypatch)
    missing_inside_repo = gen.project_root() / "webapp" / "backend" / "research" / "nope.py"
    with pytest.raises(v2.GateError, match="does not exist"):
        runner.preflight(
            MANIFEST_DIR,
            tmp_path / "out",
            gen.project_root(),
            source_paths=[missing_inside_repo],
        )


# --- real execution is unreachable -----------------------------------------


@needs_frozen
def test_execute_real_refuses_with_readiness_reasons():
    with pytest.raises(runner.ReadinessError) as excinfo:
        runner.execute_real(MANIFEST_DIR)
    message = str(excinfo.value)
    assert "execution_ready" in message
    assert "campaign_ready" in message
    assert "Stage A permits preflight and synthetic validation only" in message


def test_execute_real_refuses_even_without_inputs():
    with pytest.raises(runner.ReadinessError, match="Stage A"):
        runner.execute_real()


def test_runner_modes_exclude_real_execution():
    assert runner.MODES == ("preflight", "synthetic")
    for forbidden in ("campaign", "real", "full", "sensitivity", "execute"):
        assert forbidden not in runner.MODES


def test_cli_refuses_modes_outside_stage_a(tmp_path, capsys):
    for mode in ("campaign", "real", "full", "sensitivity"):
        code = runner.main(["--mode", mode, "--out", str(tmp_path / "out")])
        assert code == 2
    captured = capsys.readouterr()
    assert "not available in Stage A" in captured.err
    assert "separate authorization" in captured.err


# --- synthetic walkthrough --------------------------------------------------


def test_synthetic_walkthrough_end_to_end(tmp_path):
    result = runner.synthetic_walkthrough(tmp_path, rows=6)
    assert result["rows"] == 6
    assert result["generation_state"] == "completed"
    assert result["access_state"] == "completed"
    assert result["second_claim_refused"] is True
    assert result["reads_sealed_data"] is False
    assert result["fitted_model"] is False
    assert result["files"] == [
        "test_access.json",
        "test_generation.json",
        "trials_test.csv",
    ]
    campaign = Path(result["campaign_dir"])
    assert campaign.is_relative_to(tmp_path.resolve())


def test_walkthrough_is_not_repeatable(tmp_path):
    runner.synthetic_walkthrough(tmp_path, rows=4)
    with pytest.raises(v2.GateError):
        runner.synthetic_walkthrough(tmp_path, rows=4)


def test_cli_synthetic_mode_writes_only_under_the_given_directory(tmp_path, capsys):
    code = runner.main(
        [
            "--mode",
            "synthetic",
            "--out",
            str(tmp_path / "stageA"),
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--repo-root",
            str(gen.project_root()),
            "--synthetic-rows",
            "4",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    payload = json.loads(captured.out)
    assert payload["mode"] == "synthetic"
    assert payload["rows"] == 4
    assert Path(payload["campaign_dir"]).is_relative_to(tmp_path.resolve())


# --- generated-file integrity ----------------------------------------------


def test_verify_requires_a_completed_generation_record(tmp_path):
    with pytest.raises(runner.IntegrityError, match="no test_generation"):
        runner.verify_generated_trials(tmp_path)

    test_access.claim_generation(tmp_path, {"generator": "test"})
    with pytest.raises(runner.IntegrityError, match="state 'started'"):
        runner.verify_generated_trials(tmp_path)


def test_tampered_trial_bytes_fail_integrity(tmp_path):
    result = runner.synthetic_walkthrough(tmp_path)
    trials = Path(result["campaign_dir"]) / runner.TRIALS_FILENAME
    trials.write_bytes(trials.read_bytes() + b"\n")

    with pytest.raises(runner.IntegrityError, match="does not match the generation record"):
        runner.verify_generated_trials(Path(result["campaign_dir"]))
    with pytest.raises(runner.IntegrityError):
        runner.load_authorized_trials(Path(result["campaign_dir"]))


def test_missing_trial_file_fails_integrity(tmp_path):
    result = runner.synthetic_walkthrough(tmp_path)
    (Path(result["campaign_dir"]) / runner.TRIALS_FILENAME).unlink()
    with pytest.raises(runner.IntegrityError, match="trial file is missing"):
        runner.verify_generated_trials(Path(result["campaign_dir"]))


def test_load_authorized_trials_takes_no_dataframe():
    parameters = list(inspect.signature(runner.load_authorized_trials).parameters)
    assert parameters == ["out_dir"]
    with pytest.raises(TypeError):
        runner.load_authorized_trials(pd.DataFrame({"trial_id": ["x"]}))


# --- one-shot access state machine -----------------------------------------


def test_concurrent_claims_allow_exactly_one_winner(tmp_path):
    campaign = tmp_path / "campaign"
    test_access.claim_generation(campaign, {"generator": "test"})
    frame = runner._synthetic_frame(3)
    campaign.mkdir(parents=True, exist_ok=True)
    target = campaign / runner.TRIALS_FILENAME
    frame.to_csv(target, index=False)
    test_access.complete_marker(
        campaign,
        test_access.MARKER_GENERATION,
        {"trials_rows": int(len(frame)), "trials_sha256": v2.sha256_file(target)},
    )

    processes = [_subprocess_claim(campaign) for _ in range(4)]
    codes = [process.wait(timeout=120) for process in processes]
    for process in processes:
        process.stdout.close()
        process.stderr.close()

    assert codes.count(0) == 1, f"exactly one claim must win, got {codes}"
    assert test_access.marker_state(campaign, test_access.MARKER_ACCESS) == "started"


def test_malformed_access_marker_blocks_the_runner(tmp_path):
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    (campaign / test_access.MARKER_ACCESS).write_text("{not json", encoding="utf-8")
    with pytest.raises(v2.GateError):
        runner.synthetic_walkthrough(tmp_path)


# --- isolation from legacy paths -------------------------------------------


def test_runner_does_not_reference_legacy_entry_points():
    source = Path(runner.__file__).read_text(encoding="utf-8")
    for token in ("evaluate_test", "run_campaign", "run_smoke", "import phase11\n"):
        assert token not in source, f"runner must not reference {token}"
    assert "phase11_v2" in source


def test_configuration_identity_is_stable_and_content_bound():
    first = runner.configuration_identity({"mode": "preflight", "stage": "A"})
    second = runner.configuration_identity({"stage": "A", "mode": "preflight"})
    assert first == second
    assert runner.configuration_identity({"mode": "synthetic", "stage": "A"}) != first


# --- synthetic output isolation (Stage A fix) -------------------------------


def _replica(tmp_path: Path) -> tuple[Path, Path]:
    """Disposable protected-tree replica; never the real frozen directory."""
    repo = tmp_path / "repo"
    frozen = repo / "reports" / "phase11_generalization"
    (frozen / "smoke").mkdir(parents=True)
    (frozen / "smoke_invalid_scope_20261022").mkdir()
    for name in ("protocol.json", "offsets.json", "split.json", "windows_primary.json"):
        (frozen / name).write_text("{}", encoding="utf-8")
    return repo, frozen


def test_public_walkthrough_has_no_root_parameters():
    parameters = list(inspect.signature(runner.synthetic_walkthrough).parameters)
    assert parameters == ["root_dir", "rows"]
    assert "_synthetic_walkthrough" not in runner.__all__


def test_public_walkthrough_uses_canonical_roots(tmp_path, monkeypatch):
    repo, frozen = _replica(tmp_path)
    monkeypatch.setattr(runner.gen, "project_root", lambda: repo)
    with pytest.raises(runner.OutputIsolationError, match="frozen manifest tree"):
        runner.synthetic_walkthrough(frozen)
    assert not (frozen / "campaign").exists()


@needs_frozen
def test_canonical_guard_refuses_the_real_frozen_dir_without_writing():
    # resolve_output_dir is read-only, so the real path is proven refused with zero risk of
    # a write into it.
    with pytest.raises(runner.OutputIsolationError, match="frozen manifest tree"):
        runner.resolve_output_dir(
            MANIFEST_DIR, manifest_dir=MANIFEST_DIR, repo_root=gen.project_root()
        )
    assert not (MANIFEST_DIR / "campaign").exists()


@pytest.mark.parametrize("protected", ["smoke", "smoke_invalid_scope_20261022"])
def test_test_seam_rejects_protected_directories(tmp_path, protected):
    repo, frozen = _replica(tmp_path)
    target = frozen / protected
    with pytest.raises(runner.OutputIsolationError):
        runner._synthetic_walkthrough(target, rows=3, repo_root=repo, manifest_dir=frozen)
    assert not (target / "campaign").exists()


def test_test_seam_rejects_a_path_alias_into_the_frozen_tree(tmp_path):
    repo, frozen = _replica(tmp_path)
    alias = frozen / "smoke" / ".." / "campaign_alias"
    with pytest.raises(runner.OutputIsolationError):
        runner._synthetic_walkthrough(alias, rows=3, repo_root=repo, manifest_dir=frozen)
    assert not alias.exists()


def test_synthetic_walkthrough_rejects_a_file_destination(tmp_path):
    target = tmp_path / "not-a-directory"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(runner.OutputIsolationError, match="not a directory"):
        runner.synthetic_walkthrough(target)
    assert target.read_text(encoding="utf-8") == "x"


def test_synthetic_walkthrough_rejects_a_symlinked_parent(tmp_path):
    repo, frozen = _replica(tmp_path)
    link = tmp_path / "alias"
    try:
        os.symlink(frozen, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available in this environment")

    with pytest.raises(runner.OutputIsolationError):
        runner._synthetic_walkthrough(link, rows=3, repo_root=repo, manifest_dir=frozen)
    assert not (frozen / "campaign").exists()


def test_synthetic_walkthrough_rejects_a_symlinked_campaign_subdirectory(tmp_path):
    repo, frozen = _replica(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    try:
        os.symlink(frozen, root / "campaign", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available in this environment")

    with pytest.raises(runner.OutputIsolationError, match="escapes the validated output root"):
        runner._synthetic_walkthrough(root, rows=3, repo_root=repo, manifest_dir=frozen)
    assert not (frozen / "campaign").exists()


def test_rejected_walkthrough_leaves_the_replica_unchanged(tmp_path):
    repo, frozen = _replica(tmp_path)
    watched = [frozen / name for name in ("protocol.json", "split.json", "windows_primary.json")]
    before = {path.name: v2.sha256_file(path) for path in watched}
    with pytest.raises(runner.OutputIsolationError):
        runner._synthetic_walkthrough(frozen, rows=3, repo_root=repo, manifest_dir=frozen)
    after = {path.name: v2.sha256_file(path) for path in watched}
    assert after == before
    assert sorted(path.name for path in frozen.iterdir()) == [
        "offsets.json",
        "protocol.json",
        "smoke",
        "smoke_invalid_scope_20261022",
        "split.json",
        "windows_primary.json",
    ]


def test_temporary_destination_still_succeeds(tmp_path):
    result = runner.synthetic_walkthrough(tmp_path / "isolated", rows=3)
    assert result["rows"] == 3
    assert result["generation_state"] == "completed"
    assert result["second_claim_refused"] is True
