"""CLI entry point: python -m research.run_experiment --mode smoke|full"""

import argparse
import json
from pathlib import Path

from .experiment import run_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Phase 10 injection-recovery experiment.")
    parser.add_argument("--mode", choices=("smoke", "full"), default="smoke")
    parser.add_argument(
        "--out",
        default=None,
        help="output directory (defaults to reports/injection_recovery)",
    )
    args = parser.parse_args()

    def progress(done: int, total: int) -> None:
        print(f"  trial {done}/{total}", flush=True)

    summary = run_experiment(args.mode, Path(args.out) if args.out else None, progress=progress)
    print(
        json.dumps(
            {
                "status": summary["status"],
                "trials": summary["counts"]["trials_total"],
                "runtime_seconds": summary["runtime_seconds"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
