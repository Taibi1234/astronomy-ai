"""Phase 11b stage 2 tests: smoke CLI scope, dry-run, and no test access.

The execute path is exercised only with injected fakes; no detector is run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import generalization as gen  # noqa: E402
from research import phase11  # noqa: E402
from research import run_phase11 as run  # noqa: E402

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"


def test_smoke_windows_are_train_and_validation_only():
    windows = run.smoke_windows(MANIFEST_DIR)
    assert len(windows) == 12
    assert {window["quarter"] for window in windows} == {"Q00", "Q01", "Q04"}
    assert {window["split"] for window in windows} == {"train", "val"}
    assert sum(window["split"] == "train" for window in windows) == 6
    assert sum(window["split"] == "val" for window in windows) == 6


def test_smoke_scope_is_exactly_the_pre_registered_quarters():
    scope = run.assert_smoke_scope(run.smoke_windows(MANIFEST_DIR))
    assert scope == {
        "quarters": ["Q00", "Q01", "Q04"],
        "train": ["Q00", "Q04"],
        "val": ["Q01"],
        "splits": ["train", "val"],
    }


def test_smoke_scope_rejects_a_test_window():
    windows = run.smoke_windows(MANIFEST_DIR)
    poisoned = [dict(window) for window in windows]
    poisoned[0]["split"] = "test"
    with pytest.raises(phase11.GateError):
        run.assert_smoke_scope(poisoned)
    poisoned[0]["split"] = "train"
    poisoned[-1]["quarter"] = "Q02"
    with pytest.raises(phase11.GateError):
        run.assert_smoke_scope(poisoned)


def test_preflight_reports_no_test_access(tmp_path):
    plan = run.preflight(MANIFEST_DIR, tmp_path / "smoke")
    assert plan["trials"] == 168
    assert plan["windows"] == 12
    assert plan["reads_test"] is False
    assert plan["writes_test_access"] is False
    assert plan["quarters"]["train"] == ["Q00", "Q04"]
    assert plan["quarters"]["val"] == ["Q01"]


def test_preflight_refuses_manifest_dir_and_existing_ledger(tmp_path):
    with pytest.raises(phase11.GateError):
        run.preflight(MANIFEST_DIR, MANIFEST_DIR)
    out_dir = tmp_path / "smoke"
    out_dir.mkdir()
    (out_dir / "test_access.json").write_text("{}")
    with pytest.raises(phase11.GateError):
        run.preflight(MANIFEST_DIR, out_dir)


def test_dry_run_writes_nothing(tmp_path):
    out_dir = tmp_path / "smoke"
    result = run.run_smoke(MANIFEST_DIR, out_dir, execute=False)
    assert result["executed"] is False
    assert not out_dir.exists()


def test_execute_path_never_evaluates_or_writes_a_test_ledger(tmp_path):
    out_dir = tmp_path / "smoke"
    calls: dict[str, object] = {}

    def campaign(**kwargs):
        calls["campaign"] = kwargs
        windows = kwargs["windows"]
        quarters = [window["quarter"] for window in windows]
        rows = {"trial_id": [], "split": [], "quarter": [], "role": [], "injected": []}
        for index in range(168):
            rows["trial_id"].append(f"t{index}")
            rows["split"].append("train" if index % 3 else "val")
            rows["quarter"].append(quarters[index % len(quarters)])
            rows["role"].append("injection" if index % 2 else "null_window")
            rows["injected"].append(index % 2 == 1)
        return pd.DataFrame(rows)

    def fit(trials, protocol, model_id):
        calls["fit"] = {"rows": len(trials), "model_id": model_id}
        return {"model": object()}

    def freeze(out_dir_arg, **kwargs):
        calls["freeze"] = kwargs["protocol_hash"]
        (out_dir_arg / "fitted.json").write_text("{}")
        return {"fitted.json": "stub"}

    def evaluate(*_args, **_kwargs):  # pragma: no cover - must not be called
        calls["evaluate"] = True
        raise AssertionError("smoke must never evaluate test data")

    result = run.run_smoke(
        MANIFEST_DIR,
        out_dir,
        execute=True,
        campaign_fn=campaign,
        fit_fn=fit,
        freeze_fn=freeze,
        evaluate_fn=evaluate,
    )
    assert result["executed"] is True
    assert result["splits"] == ["train", "val"]
    assert result["trials"] == 168
    assert len(calls["campaign"]["windows"]) == 12
    assert {window["quarter"] for window in calls["campaign"]["windows"]} == {
        "Q00",
        "Q01",
        "Q04",
    }
    assert result["evaluate_called"] is False
    assert "evaluate" not in calls
    assert calls["campaign"]["split_group"] == "fit"
    assert calls["fit"]["model_id"] == "L7_detector_plus_clean_flux"
    assert not (out_dir / "test_access.json").exists()


def test_cli_refuses_unapproved_modes(capsys):
    assert run.main(["--mode", "full"]) == 2
    assert run.main(["--mode", "sensitivity"]) == 2
    captured = capsys.readouterr()
    assert "not enabled in stage 2" in captured.err


def test_cli_defaults_to_dry_run(tmp_path):
    exit_code = run.main(["--mode", "smoke", "--out", str(tmp_path / "smoke")])
    assert exit_code == 0
    assert not (tmp_path / "smoke").exists()


def test_window_lookup_keeps_every_window_distinct():
    windows = run.smoke_windows(MANIFEST_DIR)
    lookup = phase11.index_windows(windows)
    assert len(lookup) == len(windows) == 12
    starts = {key: window["start_index"] for key, window in lookup.items()}
    q00 = [start for (quarter, _), start in starts.items() if quarter == "Q00"]
    assert len(q00) == 2 and len(set(q00)) == 2
    slots = {(window["quarter"], window["window_index"]) for window in windows}
    assert len(slots) == 12


def test_run_smoke_rejects_unauthorised_quarters(tmp_path):
    def campaign(**_kwargs):
        return pd.DataFrame(
            {
                "trial_id": ["a"],
                "split": ["train"],
                "quarter": ["Q02"],
                "role": ["injection"],
                "injected": [True],
            }
        )

    with pytest.raises(phase11.GateError, match="unauthorised quarters"):
        run.run_smoke(
            MANIFEST_DIR,
            tmp_path / "drift",
            execute=True,
            campaign_fn=campaign,
            fit_fn=lambda *a, **k: {"model": object()},
            freeze_fn=lambda *a, **k: {},
        )


def test_run_smoke_rejects_wrong_trial_count(tmp_path):
    def campaign(**_kwargs):
        return pd.DataFrame(
            {
                "trial_id": ["a", "b", "c", "d"],
                "split": ["train", "train", "val", "val"],
                "quarter": ["Q00", "Q00", "Q01", "Q01"],
                "role": ["injection", "null_window", "injection", "null_window"],
                "injected": [True, False, True, False],
            }
        )

    with pytest.raises(phase11.GateError, match="expected 168"):
        run.run_smoke(
            MANIFEST_DIR,
            tmp_path / "short",
            execute=True,
            campaign_fn=campaign,
            fit_fn=lambda *a, **k: {"model": object()},
            freeze_fn=lambda *a, **k: {},
        )
