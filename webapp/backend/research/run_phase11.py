"""Phase 11b execution CLI. Stage 2 enables smoke only, and dry-run by default.

The smoke campaign is restricted to the three pre-registered quarters — Q00 and Q04
(train) and Q01 (validation) — so it cannot read a test quarter. It stops after freezing
the fitted state: evaluation is a separate, gated step and is never called here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import generalization as gen
from . import phase11

SMOKE_TRAIN_QUARTERS = ("Q00", "Q04")
SMOKE_VAL_QUARTERS = ("Q01",)
SMOKE_QUARTERS = SMOKE_TRAIN_QUARTERS + SMOKE_VAL_QUARTERS
ENABLED_MODES = ("smoke",)
WINDOW_DAYS = 5.0


def smoke_windows(manifest_dir: Path) -> list[dict]:
    manifest = json.loads((manifest_dir / "windows_primary.json").read_text(encoding="utf-8"))
    return [window for window in manifest["windows"] if window["quarter"] in SMOKE_QUARTERS]


def assert_smoke_scope(windows: list[dict]) -> dict:
    """The smoke campaign must be train+val only, on the pre-registered quarters."""
    if not windows:
        raise phase11.GateError("smoke selection returned no windows")
    by_quarter: dict[str, set[str]] = {}
    for window in windows:
        by_quarter.setdefault(window["quarter"], set()).add(window["split"])
    if any(len(splits) > 1 for splits in by_quarter.values()):
        raise phase11.GateError("a quarter appears in more than one split")
    splits = {next(iter(value)) for value in by_quarter.values()}
    if "test" in splits:
        raise phase11.GateError("smoke must not include test windows")
    if splits - {"train", "val"}:
        raise phase11.GateError(f"unexpected smoke splits: {sorted(splits)}")
    train = {quarter for quarter, value in by_quarter.items() if "train" in value}
    val = {quarter for quarter, value in by_quarter.items() if "val" in value}
    if train != set(SMOKE_TRAIN_QUARTERS) or val != set(SMOKE_VAL_QUARTERS):
        raise phase11.GateError(
            f"smoke quarters are {sorted(train)} train / {sorted(val)} val; "
            f"expected {list(SMOKE_TRAIN_QUARTERS)} / {list(SMOKE_VAL_QUARTERS)}"
        )
    return {
        "quarters": sorted(by_quarter),
        "train": sorted(train),
        "val": sorted(val),
        "splits": sorted(splits),
    }


def preflight(manifest_dir: Path, out_dir: Path) -> dict:
    """Resolve and validate the smoke plan without touching light curves."""
    if out_dir.resolve() == manifest_dir.resolve():
        raise phase11.GateError("smoke output must not be the manifest directory")
    if (out_dir / "test_access.json").is_file():
        raise phase11.GateError("output directory already contains a test-access record")
    windows = smoke_windows(manifest_dir)
    scope = assert_smoke_scope(windows)
    plan = phase11.plan_trials(windows, phase11.build_protocol(manifest_dir), "fit")
    return {
        "mode": "smoke",
        "window_days": WINDOW_DAYS,
        "out_dir": str(out_dir),
        "windows": len(windows),
        "trials": int(len(plan)),
        "quarters": scope,
        "writes": ["trials_fit.csv", "fitted.json", "fitted.sha256", "model.pkl"],
        "reads_test": False,
        "writes_test_access": False,
    }


def run_smoke(
    manifest_dir: Path,
    out_dir: Path,
    *,
    execute: bool = False,
    campaign_fn=None,
    fit_fn=None,
    freeze_fn=None,
    evaluate_fn=None,
) -> dict:
    """Plan (default) or execute the smoke fit stage. Never evaluates test data."""
    plan = preflight(manifest_dir, out_dir)
    if not execute:
        return {"executed": False, **plan}

    campaign = campaign_fn or phase11.run_campaign
    fit = fit_fn or phase11.fit_models
    freeze = freeze_fn or phase11.freeze_fitted
    evaluate = evaluate_fn or phase11.evaluate_test
    sentinel = _EvaluationForbidden(evaluate)

    protocol, protocol_hash = phase11.load_frozen_json(
        manifest_dir / "protocol.json",
        expected_phase=phase11.EXPECTED_PHASE,
        expected_schema=phase11.EXPECTED_SCHEMA_VERSION,
    )
    phase11.assert_protocol_manifests(protocol, manifest_dir)

    out_dir.mkdir(parents=True, exist_ok=True)
    trials = campaign(
        manifest_dir=manifest_dir,
        out_dir=out_dir,
        window_days=WINDOW_DAYS,
        split_group="fit",
        windows=smoke_windows(manifest_dir),
    )
    if set(trials["split"].unique()) - {"train", "val"}:
        raise phase11.GateError("smoke campaign returned non-fitting rows")
    unexpected = set(trials["quarter"].unique()) - set(SMOKE_QUARTERS)
    if unexpected:
        raise phase11.GateError(f"smoke campaign used unauthorised quarters: {sorted(unexpected)}")
    if len(trials) != plan["trials"]:
        raise phase11.GateError(
            f"smoke campaign produced {len(trials)} trials; expected {plan['trials']}"
        )

    fitted = fit(trials, protocol, "L7_detector_plus_clean_flux")
    frozen = freeze(
        out_dir,
        fitted=fitted,
        model=fitted["model"],
        trials=trials,
        protocol=protocol,
        protocol_hash=protocol_hash,
    )
    if (out_dir / "test_access.json").is_file():
        raise phase11.GateError("smoke stage must not create a test-access record")
    return {
        "executed": True,
        "mode": "smoke",
        "trials": int(len(trials)),
        "splits": sorted(trials["split"].unique()),
        "artifacts": frozen,
        "test_access": False,
        "evaluate_called": sentinel.called,
    }


class _EvaluationForbidden:
    """Sentinel used only to assert that smoke never calls the evaluator."""

    def __init__(self, evaluate_fn) -> None:
        self.evaluate_fn = evaluate_fn
        self.called = False

    def __call__(self, *args, **kwargs):  # pragma: no cover - defensive
        self.called = True
        raise phase11.GateError("smoke must not evaluate test data")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 11b execution CLI (smoke only, stage 2).")
    parser.add_argument("--mode", choices=("smoke", "full", "sensitivity"), default="smoke")
    parser.add_argument("--manifest-dir", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--execute", action="store_true", help="run the smoke fit stage")
    args = parser.parse_args(argv)

    if args.mode not in ENABLED_MODES:
        print(
            f"mode '{args.mode}' is not enabled in stage 2; only 'smoke' may run "
            "(full and sensitivity need separate approval)",
            file=sys.stderr,
        )
        return 2

    manifest_dir = (
        Path(args.manifest_dir)
        if args.manifest_dir
        else gen.project_root() / "reports" / "phase11_generalization"
    )
    out_dir = Path(args.out) if args.out else manifest_dir / "smoke"
    result = run_smoke(manifest_dir, out_dir, execute=args.execute)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "SMOKE_QUARTERS",
    "SMOKE_TRAIN_QUARTERS",
    "SMOKE_VAL_QUARTERS",
    "assert_smoke_scope",
    "main",
    "preflight",
    "run_smoke",
    "smoke_windows",
]
