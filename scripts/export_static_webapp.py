"""Export the read-only observatory as static files for GitHub Pages.

This script calls only the existing read-only backend handlers. It reads committed
CSVs and saved reports, writes JSON below ``webapp/frontend/public/api``, and copies
allowlisted recovery artifacts. It does not run a scientific campaign, train a
model, access sealed test quarters, or modify any source observation or report.

Run from the repository root after installing ``webapp/backend/requirements-web.txt``:

    python scripts/export_static_webapp.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from fastapi.encoders import jsonable_encoder

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "webapp" / "backend"
OUTPUT_ROOT = PROJECT_ROOT / "webapp" / "frontend" / "public" / "api"

# app.py and transit_injection.py are sibling modules in webapp/backend.
sys.path.insert(0, str(BACKEND_DIR))
import app as backend  # noqa: E402


def write_json(relative_path: str, payload: object) -> Path:
    """Write one deterministic, strict JSON response below the export root."""
    destination = (OUTPUT_ROOT / relative_path).resolve()
    if not destination.is_relative_to(OUTPUT_ROOT.resolve()):
        raise ValueError(f"Export path escapes the static data root: {relative_path}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = jsonable_encoder(payload)
    destination.write_text(
        json.dumps(encoded, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )
    return destination


def export_transit_injection() -> int:
    """Precompute every control combination exposed by the existing frontend."""
    exported = 0
    for mission in sorted(backend.DATASETS):
        for depth in backend.transit_injection.SUPPORTED_DEPTHS_PPM:
            default = backend.transit_injection_preview(
                mission=mission,
                depth_ppm=depth,
                center_index=None,
            )
            write_json(f"transit-injection/{mission}/{depth}/default.json", default)
            exported += 1

            for center in default["available_centers"]:
                response = backend.transit_injection_preview(
                    mission=mission,
                    depth_ppm=depth,
                    center_index=center["index"],
                )
                write_json(
                    f"transit-injection/{mission}/{depth}/{center['index']}.json",
                    response,
                )
                exported += 1
    return exported


def export_recovery_artifacts() -> int:
    """Copy only filenames explicitly allowlisted by the existing backend."""
    exported = 0
    for name, (relative_path, _media_type) in backend.RECOVERY_ARTIFACTS.items():
        source = backend.RECOVERY_DIR / relative_path
        if not source.is_file():
            raise FileNotFoundError(f"Required recovery artifact is missing: {source}")

        destination = OUTPUT_ROOT / "injection-recovery" / "artifacts" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        exported += 1
    return exported


def main() -> None:
    # This directory contains generated public copies only; source data and reports
    # are outside it and are never removed or rewritten.
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    OUTPUT_ROOT.mkdir(parents=True)

    write_json("health.json", backend.health())
    write_json("project.json", backend.project())
    write_json("artifacts.json", backend.artifacts())
    write_json("ml-results.json", backend.ml_results())
    write_json(
        "injection-recovery/status.json",
        backend.injection_recovery_status(),
    )
    write_json(
        "injection-recovery/results.json",
        backend.injection_recovery_results(),
    )

    for mission in sorted(backend.DATASETS):
        write_json(
            f"lightcurve/{mission}.json",
            backend.get_lightcurve(mission=mission, max_points=10000),
        )

    injection_count = export_transit_injection()
    artifact_count = export_recovery_artifacts()
    files = [path for path in OUTPUT_ROOT.rglob("*") if path.is_file()]
    total_bytes = sum(path.stat().st_size for path in files)

    print(
        f"Exported {len(files)} static files ({total_bytes / 1024 / 1024:.2f} MiB) "
        f"to {OUTPUT_ROOT.relative_to(PROJECT_ROOT)}"
    )
    print(
        f"Transit-injection responses: {injection_count}; "
        f"recovery artifacts: {artifact_count}; runner enabled: {backend.RUNNER_ENABLED}"
    )


if __name__ == "__main__":
    main()
