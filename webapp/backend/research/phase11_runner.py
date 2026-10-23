"""Phase 11 Stage A runner: preflight and synthetic validation only.

Design contract
---------------
* **No real execution path exists.** :func:`execute_real` always raises; Stage A cannot run
  the campaign even if the protocol readiness flags were flipped. Real execution needs a
  separate Stage B authorization and a code change, never a flag.
* **Preflight answers, it does not act.** :func:`preflight` validates protocol identity,
  manifest/offset hashes, output isolation, provenance and the clean tree, then reports the
  protocol's readiness blockers. It reads no trial data and writes nothing.
* **Synthetic walkthrough is the only thing that writes.** It lives entirely under a
  caller-supplied temporary root, uses generated rows (never scientific inputs) and exists
  to exercise the one-shot state machine plus the trial-file integrity contract.
* **Integrity before evaluation.** :func:`verify_generated_trials` recomputes the hash of
  the generated trial file and compares it with the value recorded in the completed
  generation marker. :func:`load_authorized_trials` accepts only a directory, never a
  caller-supplied DataFrame, so the future evaluator cannot bypass the artifact path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import NoReturn

import pandas as pd

from . import generalization as gen
from . import phase11_v2 as v2
from . import safeguards, test_access
from .errors import GateError

STAGE = "A"
MODES = ("preflight", "synthetic")
TRIALS_FILENAME = "trials_test.csv"
SYNTHETIC_COLUMNS = (
    "trial_id",
    "split",
    "role",
    "quarter",
    "injected",
    "snr",
    "requested_depth_ppm",
    "source",
)
V1_STAGE0_FILES = ("protocol.json", "offsets.json", "protocol.sha256", "offsets.sha256")


class RunnerError(GateError):
    """Base class for every Stage A runner refusal."""


class ReadinessError(RunnerError):
    """Real execution was requested but is not authorized."""


class IntegrityError(RunnerError):
    """The generated trial artifact does not match its generation record."""


class OutputIsolationError(RunnerError):
    """The requested output location is not safe for Stage A."""


# --- identity helpers -------------------------------------------------------


def configuration_identity(config: dict) -> str:
    """Stable hash of the resolved run configuration."""
    payload = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def execution_blockers(protocol: dict) -> list[str]:
    """Every reason the protocol does not authorize execution, in a stable order."""
    blockers: list[str] = []
    if protocol.get("campaign_ready") is not True:
        blockers.append("campaign_ready is not true")
    if protocol.get("execution_ready") is not True:
        blockers.append("execution_ready is not true")
    status = str(protocol.get("status", "")).lower()
    if "not authorized" in status or "proposal only" in status:
        blockers.append("protocol status declares it is not authorized for execution")
    proposal = protocol.get("proposal_record")
    if isinstance(proposal, dict) and "not authorized" in str(proposal.get("status", "")).lower():
        blockers.append("proposal_record declares it is not authorized for execution")
    return blockers


def resolve_output_dir(out_dir: Path, *, manifest_dir: Path, repo_root: Path) -> Path:
    """Reject protected, frozen-tree, v1-stage-0 and campaign-state destinations."""
    resolved = Path(out_dir).resolve()
    frozen = Path(manifest_dir).resolve()
    if resolved.exists() and not resolved.is_dir():
        raise OutputIsolationError(
            f"output path {resolved} exists and is not a directory; refusing to use it as a "
            "campaign output root"
        )
    if resolved == frozen or resolved.is_relative_to(frozen):
        raise OutputIsolationError(
            f"output directory {resolved} is inside the frozen manifest tree {frozen}; "
            "Stage A requires a dedicated temporary or explicitly isolated location"
        )
    present = [name for name in V1_STAGE0_FILES if (resolved / name).exists()]
    if present:
        raise OutputIsolationError(
            f"output directory {resolved} holds v1 stage-0 artifacts {present}; refusing to "
            "mix v1 and v2 outputs"
        )
    try:
        safeguards.assert_no_campaign_state(resolved, purpose="stage A runner")
        safeguards.assert_safe_output(resolved, root=repo_root, purpose="stage A runner")
    except safeguards.SafeguardError as exc:
        raise OutputIsolationError(str(exc)) from exc
    return resolved


# --- preflight --------------------------------------------------------------


def preflight(
    manifest_dir: Path,
    out_dir: Path,
    repo_root: Path,
    *,
    source_paths: list[Path] | None = None,
    config: dict | None = None,
) -> dict:
    """Validate everything a real run would need, and report whether it is authorized."""
    resolved = resolve_output_dir(out_dir, manifest_dir=manifest_dir, repo_root=repo_root)
    paths = (
        list(source_paths)
        if source_paths is not None
        else [repo_root / "webapp" / "backend" / "research" / "phase11_runner.py"]
    )
    preconditions = v2.campaign_preconditions(
        Path(manifest_dir), resolved, Path(repo_root), source_paths=paths
    )
    protocol, protocol_hash = v2.load_protocol_v21(Path(manifest_dir) / v2.AUTHORIZED_PROTOCOL_NAME)
    blockers = execution_blockers(protocol)
    run_config = dict(config or {"mode": "preflight", "stage": STAGE})
    return {
        "stage": STAGE,
        "mode": "preflight",
        "protocol_name": v2.AUTHORIZED_PROTOCOL_NAME,
        "protocol_version": protocol["version"],
        "protocol_hash": protocol_hash,
        "offsets_sha256": preconditions["offsets_sha256"],
        "manifests": preconditions["manifests"],
        "provenance": preconditions["provenance"],
        "configuration": run_config,
        "configuration_sha256": configuration_identity(run_config),
        "execution_blockers": blockers,
        "execution_authorized": not blockers,
        "reads_test": False,
        "writes": [],
    }


def execute_real(*_args, **_kwargs) -> NoReturn:
    """Refuse real execution unconditionally. Stage A has no campaign path."""
    blockers: list[str] = []
    manifest_dir = _args[0] if _args else None
    if manifest_dir is not None:
        try:
            protocol, _digest = v2.load_protocol_v21(
                Path(manifest_dir) / v2.AUTHORIZED_PROTOCOL_NAME
            )
            blockers = execution_blockers(protocol)
        except GateError as exc:
            raise ReadinessError(
                f"real execution refused: the protocol cannot be validated ({exc})"
            ) from exc
    if not blockers:
        blockers.append("protocol readiness flags alone are not execution authorization")
    blockers.append("Stage A permits preflight and synthetic validation only")
    raise ReadinessError("real campaign execution is not authorized: " + "; ".join(blockers))


# --- generated-file integrity ----------------------------------------------


def verify_generated_trials(out_dir: Path) -> dict:
    """Recompute the trial-file hash and compare it with the generation record."""
    out = Path(out_dir)
    state = test_access.marker_state(out, test_access.MARKER_GENERATION)
    if state is None:
        raise IntegrityError(f"no {test_access.MARKER_GENERATION} in {out}; nothing to verify")
    if state != "completed":
        raise IntegrityError(
            f"generation marker is in state {state!r}; only a completed generation record "
            "can be evaluated"
        )
    record = json.loads((out / test_access.MARKER_GENERATION).read_text(encoding="utf-8"))
    recorded = record.get("trials_sha256")
    if not isinstance(recorded, str) or len(recorded) != 64:
        raise IntegrityError("generation record has no usable trials_sha256")
    trials = out / TRIALS_FILENAME
    if not trials.is_file():
        raise IntegrityError(f"generated trial file is missing: {trials}")
    actual = v2.sha256_file(trials)
    if actual != recorded:
        raise IntegrityError(
            f"generated trial file hash {actual} does not match the generation record "
            f"{recorded}; refusing to evaluate"
        )
    return {
        "trials_path": str(trials),
        "trials_sha256": actual,
        "trials_rows": record.get("trials_rows"),
    }


def load_authorized_trials(out_dir: Path) -> pd.DataFrame:
    """Load trials only through the hash-verified artifact path.

    The signature deliberately takes a directory, never a DataFrame: there is no argument
    through which a caller could inject unverified rows.
    """
    info = verify_generated_trials(out_dir)
    frame = pd.read_csv(Path(out_dir) / TRIALS_FILENAME)
    recorded_rows = info.get("trials_rows")
    if isinstance(recorded_rows, int) and recorded_rows != len(frame):
        raise IntegrityError(
            f"generated trial file has {len(frame)} rows but the generation record says "
            f"{recorded_rows}"
        )
    return frame


# --- synthetic walkthrough ---------------------------------------------------


def _synthetic_frame(rows: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trial_id": f"SYN-{index:03d}",
                "split": "test",
                "role": "injection",
                "quarter": f"Q{index % 5:02d}",
                "injected": 1 if index % 2 == 0 else 0,
                "snr": float(index % 7) + 0.5,
                "requested_depth_ppm": 100.0,
                "source": "synthetic-fixture",
            }
            for index in range(rows)
        ],
        columns=list(SYNTHETIC_COLUMNS),
    )


def _synthetic_walkthrough(
    root_dir: Path,
    *,
    rows: int,
    repo_root: Path,
    manifest_dir: Path,
) -> dict:
    """Implementation seam with explicit roots. Production callers use the wrapper below.

    Tests use this to point at a disposable protected-tree replica, so a failing regression
    test can never write into the real frozen directory.
    """
    repo = Path(repo_root).resolve()
    frozen = Path(manifest_dir).resolve()
    root = resolve_output_dir(root_dir, manifest_dir=frozen, repo_root=repo)
    campaign = root / "campaign"
    if not campaign.resolve().is_relative_to(root):
        raise OutputIsolationError(
            f"campaign directory {campaign.resolve()} escapes the validated output root {root}"
        )
    test_access.assert_no_markers(campaign)

    frame = _synthetic_frame(rows)
    campaign.mkdir(parents=True, exist_ok=True)
    # TOCTOU mitigation: re-validate the directory that actually exists before any marker or
    # trial file is written. A swap between validation and mkdir can leave at most an empty
    # directory behind; it cannot place a marker or a trial file inside protected evidence.
    resolved_campaign = campaign.resolve()
    if not resolved_campaign.is_relative_to(root):
        raise OutputIsolationError(
            f"campaign directory {resolved_campaign} left the validated root {root} after "
            "creation; refusing to write any artifact"
        )
    resolve_output_dir(resolved_campaign, manifest_dir=frozen, repo_root=repo)

    test_access.claim_generation(campaign, {"generator": "stage-A-synthetic", "stage": STAGE})
    target = campaign / TRIALS_FILENAME
    frame.to_csv(target, index=False)
    test_access.complete_marker(
        campaign,
        test_access.MARKER_GENERATION,
        {"trials_rows": int(len(frame)), "trials_sha256": v2.sha256_file(target)},
    )

    integrity = verify_generated_trials(campaign)
    loaded = load_authorized_trials(campaign)
    test_access.claim_access(
        campaign,
        {"evaluator": "stage-A-synthetic", "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256},
    )
    test_access.complete_marker(
        campaign, test_access.MARKER_ACCESS, {"synthetic": True, "rows": int(len(loaded))}
    )

    second_claim_refused = False
    try:
        test_access.claim_access(campaign, {"evaluator": "second attempt"})
    except GateError:
        second_claim_refused = True

    return {
        "stage": STAGE,
        "mode": "synthetic",
        "root": str(root),
        "campaign_dir": str(campaign),
        "rows": int(len(frame)),
        "trials_sha256": integrity["trials_sha256"],
        "generation_state": test_access.marker_state(campaign, test_access.MARKER_GENERATION),
        "access_state": test_access.marker_state(campaign, test_access.MARKER_ACCESS),
        "second_claim_refused": second_claim_refused,
        "files": sorted(path.name for path in campaign.iterdir()),
        "reads_sealed_data": False,
        "fitted_model": False,
    }


def synthetic_walkthrough(root_dir: Path, *, rows: int = 6) -> dict:
    """Production entry point. Roots are canonical and cannot be overridden.

    Test-only configurability lives in ``_synthetic_walkthrough``, so no production caller
    can weaken output isolation by supplying arbitrary repository or manifest roots.
    """
    repo = gen.project_root()
    return _synthetic_walkthrough(
        root_dir,
        rows=rows,
        repo_root=repo,
        manifest_dir=repo / "reports" / "phase11_generalization",
    )


# --- CLI --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phase11_runner",
        description="Phase 11 Stage A runner (preflight and synthetic validation only).",
    )
    parser.add_argument("--mode", default="preflight", help="preflight | synthetic")
    parser.add_argument("--manifest-dir", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--synthetic-rows", type=int, default=6)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode not in MODES:
        print(
            f"mode {args.mode!r} is not available in Stage A; permitted modes: "
            f"{list(MODES)}. Real campaign execution requires a separate authorization.",
            file=sys.stderr,
        )
        return 2
    repo_root = Path(args.repo_root) if args.repo_root else Path.cwd()
    manifest_dir = (
        Path(args.manifest_dir)
        if args.manifest_dir
        else repo_root / "reports" / "phase11_generalization"
    )
    out_dir = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="phase11_stageA_"))

    try:
        if args.mode == "synthetic":
            # Canonical roots only: synthetic outputs are guarded against the real project,
            # never against caller-supplied roots.
            result = synthetic_walkthrough(out_dir, rows=args.synthetic_rows)
        else:
            result = preflight(manifest_dir, out_dir, repo_root)
    except GateError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI glue
    raise SystemExit(main())


__all__ = [
    "MODES",
    "STAGE",
    "TRIALS_FILENAME",
    "IntegrityError",
    "OutputIsolationError",
    "ReadinessError",
    "RunnerError",
    "build_parser",
    "configuration_identity",
    "execute_real",
    "execution_blockers",
    "load_authorized_trials",
    "main",
    "preflight",
    "resolve_output_dir",
    "synthetic_walkthrough",
    "verify_generated_trials",
]
