"""Phase 11 protocol-v2 CLI. Preflight only; there is no execution path.

The CLI exists so that any future campaign must pass the frozen v2.3 preflight: exact
protocol hash, manifest hashes and structure, offsets hash, absent test markers, absent
fitted artifact, and a clean tracked tree. It deliberately imports nothing from the v1
runner and exposes no `--execute` flag, so there is no fallback to the v1 path.

Exit codes: 0 success, 2 refused by the CLI itself, 3 refused by a preflight gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import generalization as gen
from . import phase11_v2 as v2

MODE_PREFLIGHT = "preflight"
ENABLED_MODES = (MODE_PREFLIGHT,)
KNOWN_MODES = (MODE_PREFLIGHT, "smoke", "full", "sensitivity")
EXIT_OK = 0
EXIT_CLI_REFUSED = 2
EXIT_GATE_REFUSED = 3
DEFAULT_SOURCE_FILES = ("research/phase11_v2.py", "research/run_phase11_v2.py")


def default_source_paths(repo_root: Path) -> list[Path]:
    """The runner sources whose hashes are bound into provenance."""
    backend = repo_root / "webapp" / "backend"
    return [backend / relative for relative in DEFAULT_SOURCE_FILES]


def preflight(
    manifest_dir: Path,
    out_dir: Path,
    repo_root: Path,
    *,
    source_paths: list[Path] | None = None,
) -> dict:
    """Run the frozen preflight; raises GateError on any failure. Writes nothing."""
    paths = default_source_paths(repo_root) if source_paths is None else list(source_paths)
    result = v2.campaign_preconditions(manifest_dir, out_dir, repo_root, source_paths=paths)
    return {
        "mode": MODE_PREFLIGHT,
        "protocol_version": result["protocol_version"],
        "protocol_hash": result["protocol_hash"],
        "offsets_sha256": result["offsets_sha256"],
        "manifests": result["manifests"],
        "provenance": result["provenance"],
        "reads_test": False,
        "writes": [],
        "campaign_authorized": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_phase11_v2",
        description="Phase 11 protocol-v2 preflight (no campaign execution path).",
    )
    parser.add_argument("--mode", choices=KNOWN_MODES, default=MODE_PREFLIGHT)
    parser.add_argument("--manifest-dir", default=None)
    parser.add_argument("--out", default=None, help="campaign output directory to preflight")
    parser.add_argument("--repo-root", default=None)
    parser.add_argument(
        "--source",
        action="append",
        default=None,
        help="source file to bind into provenance (repeatable); defaults to the runners",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.mode not in ENABLED_MODES:
        print(
            f"mode {args.mode!r} is not enabled. This CLI supports preflight only; "
            "smoke, full and sensitivity campaigns require separate authorization, and "
            "there is no fallback to the v1 runner.",
            file=sys.stderr,
        )
        return EXIT_CLI_REFUSED

    repo_root = Path(args.repo_root) if args.repo_root else gen.project_root()
    manifest_dir = (
        Path(args.manifest_dir)
        if args.manifest_dir
        else repo_root / "reports" / "phase11_generalization"
    )
    if not args.out:
        print(
            "preflight requires --out: the output directory is part of what is checked",
            file=sys.stderr,
        )
        return EXIT_CLI_REFUSED

    source_paths = [Path(item) for item in args.source] if args.source else None
    try:
        result = preflight(manifest_dir, Path(args.out), repo_root, source_paths=source_paths)
    except v2.GateError as exc:
        print(f"preflight refused: {exc}", file=sys.stderr)
        return EXIT_GATE_REFUSED

    print(json.dumps(result, indent=2))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - CLI glue
    raise SystemExit(main())


__all__ = [
    "DEFAULT_SOURCE_FILES",
    "ENABLED_MODES",
    "EXIT_CLI_REFUSED",
    "EXIT_GATE_REFUSED",
    "EXIT_OK",
    "KNOWN_MODES",
    "MODE_PREFLIGHT",
    "build_parser",
    "default_source_paths",
    "main",
    "preflight",
]
