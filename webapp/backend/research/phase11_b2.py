"""Phase 11 Stage B2: v2 test-split generator (design §5.8).

Synthetic arrays only. The generator writes ``trials_test.csv`` under a dedicated campaign
directory, behind the shared one-shot generation claim, and completes that claim with the file
hash so :func:`phase11_runner.verify_generated_trials` can recompute it. It reads no quarter CSV,
opens no sealed trial, evaluates nothing and adds no execution mode: real campaign execution
remains the unconditional refusal in ``phase11_runner.execute_real``.

Ordering on every call (fail closed, no side effect before a gate passes):

1. approved-mode gate (reused from B1; one definition of the mode vocabulary);
2. authenticated-protocol gate on the B0 view and the pinned v2.3 hash;
3. campaign-directory isolation, before anything is created or written;
4. the frozen split manifest is hash-verified and supplies the only quarters that may be
   generated as test rows;
5. the frozen fitted state must exist and load under the pinned protocol;
6. no campaign marker may exist;
7. rows are built from synthetic arrays, then the generation claim is taken, the file is
   written and the claim is completed with the row count and SHA-256.

``resolve_output_dir`` cannot be applied to the campaign directory itself: it deliberately
refuses a directory that already holds campaign state, while generation *requires* the frozen
fitted state in that same directory. B2 therefore applies the narrower, equally fail-closed
checks in :func:`resolve_campaign_dir` (frozen-manifest-tree refusal, protected-directory
refusal, file-in-place refusal) and re-validates the directory after creation and before every
write.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import transit_injection as ti

from . import phase11, safeguards, test_access
from . import phase11_b1 as b1
from . import phase11_b2a as b2a
from . import phase11_v2 as v2
from .features import FEATURE_NAMES, time_domain_features
from .phase11 import GateError
from .phase11_runner import OutputIsolationError

MODE_SYNTHETIC = b1.MODE_SYNTHETIC
APPROVED_MODES = b1.APPROVED_MODES
TEST_SPLIT = "test"
TRIALS_FILENAME = "trials_test.csv"
GENERATOR_NAME = "phase11-v2-b2"
DELTA_COLUMNS = ("delta_true_days", "delta_est_days")
REQUIRED_TRUTH_COLUMNS = (*DELTA_COLUMNS, "injected", "requested_depth_ppm", "role")
DETECTOR_COLUMNS = ("snr", "depth_est_ppm", "sigma_ppm")


@dataclass(frozen=True)
class GenerationSpec:
    """Everything that shapes the synthetic test rows; no configuration authority of its own."""

    split_map: Mapping[str, str]
    seed: int
    windows_per_quarter: int = 1
    depths_ppm: Sequence[float] = (150.0, 300.0)
    geometry: b2a.Geometry | None = None
    model_id: str | None = None


# --- gates -------------------------------------------------------------------


def assert_test_split_map(split_map: object, allowed_quarters: set[str]) -> dict[str, str]:
    """Refuse any non-test split and any quarter the frozen split manifest did not assign."""
    if not isinstance(split_map, Mapping) or not split_map:
        raise GateError("split_map must be a non-empty mapping of quarter -> 'test'")
    approved: dict[str, str] = {}
    for quarter, split in split_map.items():
        if not isinstance(quarter, str) or not quarter:
            raise GateError("split_map keys must be non-empty quarter identifiers")
        if split != TEST_SPLIT:
            raise GateError(
                f"split {split!r} for {quarter} is not {TEST_SPLIT!r}; B2 generates the test "
                "split only, and refuses before any row is built"
            )
        if quarter not in allowed_quarters:
            raise GateError(
                f"{quarter} is not a test quarter in the frozen split manifest; refusing to "
                "generate it as test rows"
            )
        approved[quarter] = split
    return approved


def frozen_test_quarters(manifest_dir: Path, effective: Mapping) -> set[str]:
    """Hash-verify the frozen manifests, then read the test quarters from split.json."""
    v2.validate_manifests(Path(manifest_dir), dict(effective))
    payload = json.loads((Path(manifest_dir) / "split.json").read_text(encoding="utf-8"))
    quarters = payload.get("quarters")
    if not isinstance(quarters, Mapping):
        raise GateError("frozen split manifest has no quarters mapping")
    allowed = {
        str(quarter)
        for quarter, meta in quarters.items()
        if isinstance(meta, Mapping) and meta.get("split") == TEST_SPLIT
    }
    if not allowed:
        raise GateError("frozen split manifest declares no test quarters")
    return allowed


def resolve_campaign_dir(out_dir: Path, *, manifest_dir: Path, repo_root: Path) -> Path:
    """Narrow, fail-closed isolation for a directory that may already hold fitted state."""
    resolved = Path(out_dir).resolve()
    frozen = Path(manifest_dir).resolve()
    if resolved == frozen or resolved.is_relative_to(frozen):
        raise OutputIsolationError(
            f"campaign directory {resolved} is inside the frozen manifest tree {frozen}; "
            "test trials may only be generated in a dedicated campaign directory"
        )
    if resolved.exists() and not resolved.is_dir():
        raise OutputIsolationError(
            f"campaign path {resolved} exists and is not a directory; refusing to generate "
            "test trials there"
        )
    try:
        safeguards.assert_not_protected_directory(
            resolved, root=Path(repo_root).resolve(), purpose="B2 test-trial generation"
        )
    except safeguards.SafeguardError as exc:
        raise OutputIsolationError(str(exc)) from exc
    return resolved


def _assert_fitted_state(campaign: Path) -> dict:
    phase11.assert_test_generation_allowed(campaign)
    return v2.load_fitted_v21(campaign, v2.AUTHORIZED_PROTOCOL_SHA256)


def _assert_no_markers(campaign: Path) -> None:
    test_access.assert_no_markers(campaign)


def model_feature_columns(effective: Mapping, model_id: str | None) -> tuple[str, list[str]]:
    """Resolve the model's feature columns from the B0 view; refuse unbuildable columns."""
    if not isinstance(effective, Mapping):
        raise GateError("effective protocol must be a mapping produced by B0")
    features_block = effective.get("features")
    if not isinstance(features_block, Mapping):
        raise GateError("effective protocol has no features block")
    if model_id is None:
        model_id = features_block.get("primary_model")
    if not isinstance(model_id, str) or not model_id:
        raise GateError("no model id: pass model_id or use a view that names primary_model")
    columns = phase11.feature_columns(dict(effective), model_id)
    buildable = set(DETECTOR_COLUMNS) | set(FEATURE_NAMES)
    declared = set(features_block.get("detector_outputs") or ()) | set(
        features_block.get("flux_features") or ()
    )
    unbuildable = sorted(declared - buildable)
    if unbuildable:
        raise GateError(f"B2 cannot produce the declared feature columns {unbuildable}")
    unknown = sorted(set(columns) - buildable)
    if unknown:
        raise GateError(f"B2 cannot produce the requested feature columns {unknown}")
    return model_id, columns


def _validate_geometry(geometry: object) -> b2a.Geometry:
    if not isinstance(geometry, b2a.Geometry):
        raise GateError("geometry must be a phase11_b2a.Geometry instance")
    for name in ("window_days", "cadence_days", "noise_ppm"):
        value = getattr(geometry, name)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise GateError(f"{name} must be a real number")
        if not np.isfinite(value) or value <= 0:
            raise GateError(f"{name} must be finite and positive")
    if geometry.mission not in ti.BJD_REFERENCE:
        raise GateError(f"unknown mission {geometry.mission!r}")
    return geometry


def _validate_depths(depths_ppm: Sequence[float]) -> list[float]:
    if isinstance(depths_ppm, (str, bytes)) or not isinstance(depths_ppm, Sequence):
        raise GateError("depths_ppm must be a sequence of positive depths")
    depths = []
    for depth in depths_ppm:
        value = float(depth)
        if not np.isfinite(value) or value <= 0:
            raise GateError(f"injected depths must be finite and positive, got {depth!r}")
        depths.append(value)
    if not depths:
        raise GateError("depths_ppm must contain at least one positive depth")
    return sorted(set(depths))


# --- row construction --------------------------------------------------------


def _test_row(
    *,
    quarter: str,
    window_index: int,
    noise_condition: str,
    requested_depth_ppm: float,
    delta_true_days: float,
    times: np.ndarray,
    flux: np.ndarray,
    mission: str,
) -> dict:
    detection = b2a.detect_window(times, flux, mission)
    role = b2a.ROLE_NULL if requested_depth_ppm == 0 else b2a.ROLE_INJECTION
    return {
        "trial_id": f"{quarter}-{window_index}-d{int(requested_depth_ppm)}-{noise_condition}",
        "quarter": quarter,
        "window_index": int(window_index),
        "split": TEST_SPLIT,
        "role": role,
        "requested_depth_ppm": float(requested_depth_ppm),
        "injected": bool(requested_depth_ppm > 0),
        "noise_condition": noise_condition,
        "source": b2a.SOURCE,
        "delta_true_days": float(delta_true_days),
        "delta_est_days": float(detection["delta"]),
        "snr": float(detection["snr"]),
        "depth_est_ppm": float(detection["depth_ppm"]),
        "sigma_ppm": float(detection["sigma_ppm"]),
        **time_domain_features(times, flux),
    }


def _validate_build_inputs(
    seed: object,
    windows_per_quarter: object,
    depths_ppm: Sequence[float],
    geometry: b2a.Geometry | None,
) -> tuple[b2a.Geometry, list[float]]:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise GateError("seed must be an integer")
    if (
        isinstance(windows_per_quarter, bool)
        or not isinstance(windows_per_quarter, int)
        or windows_per_quarter < 1
    ):
        raise GateError("windows_per_quarter must be a positive integer")
    resolved = _validate_geometry(b2a.Geometry() if geometry is None else geometry)
    return resolved, _validate_depths(depths_ppm)


def _generate_rows(
    *,
    splits: Mapping[str, str],
    conditions: Sequence[str],
    depths: Sequence[float],
    geometry: b2a.Geometry,
    windows_per_quarter: int,
    seed: int,
) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    for quarter in sorted(splits):
        for window_index in range(windows_per_quarter):
            for noise_condition in conditions:
                delta = float(rng.uniform(-0.15, 0.15))
                for depth in (0.0, *depths):
                    times, flux = b2a.synthetic_window(
                        window_days=float(geometry.window_days),
                        cadence_days=float(geometry.cadence_days),
                        noise_condition=noise_condition,
                        requested_depth_ppm=float(depth),
                        rng=rng,
                        mission=geometry.mission,
                        noise_ppm=float(geometry.noise_ppm),
                        delta_days=delta,
                    )
                    rows.append(
                        _test_row(
                            quarter=quarter,
                            window_index=window_index,
                            noise_condition=noise_condition,
                            requested_depth_ppm=float(depth),
                            delta_true_days=delta,
                            times=times,
                            flux=flux,
                            mission=geometry.mission,
                        )
                    )
    return rows


def assert_test_frame(frame: pd.DataFrame, columns: Sequence[str]) -> None:
    """Post-conditions on a generated test frame; every failure is a gate failure."""
    if frame.empty:
        raise GateError("B2 built no test rows")
    if set(frame["split"].unique()) != {TEST_SPLIT}:
        raise GateError("B2 frame must contain test-split rows only")
    if bool((frame["injected"].astype(bool) != (frame["requested_depth_ppm"] > 0)).any()):
        raise GateError("label invariant violated: injected != (requested_depth_ppm > 0)")
    if frame[frame["role"] == b2a.ROLE_NULL].empty:
        raise GateError("test rows must include null windows for the false-positive rate")
    missing = [
        column for column in (*columns, *REQUIRED_TRUTH_COLUMNS) if column not in frame.columns
    ]
    if missing:
        raise GateError(f"B2 frame is missing required columns {missing}")


def build_test_frame(
    *,
    effective: Mapping,
    split_map: Mapping[str, str],
    seed: int,
    allowed_quarters: set[str],
    windows_per_quarter: int = 1,
    depths_ppm: Sequence[float] = (150.0, 300.0),
    geometry: b2a.Geometry | None = None,
    model_id: str | None = None,
) -> pd.DataFrame:
    """Build synthetic test-split rows. No file is opened, created or written here."""
    geometry, depths = _validate_build_inputs(seed, windows_per_quarter, depths_ppm, geometry)
    splits = assert_test_split_map(split_map, allowed_quarters)
    _, columns = model_feature_columns(effective, model_id)
    conditions = b2a.validate_conditions(effective)

    frame = pd.DataFrame(
        _generate_rows(
            splits=splits,
            conditions=conditions,
            depths=depths,
            geometry=geometry,
            windows_per_quarter=windows_per_quarter,
            seed=seed,
        )
    )
    assert_test_frame(frame, columns)
    return frame


# --- gated generation --------------------------------------------------------


def generate_test_trials(
    *,
    effective: Mapping,
    out_dir: Path,
    manifest_dir: Path,
    repo_root: Path,
    spec: GenerationSpec,
    mode: object = MODE_SYNTHETIC,
) -> dict:
    """Generate, claim and complete the synthetic test-trial artifact."""
    b1.assert_approved_mode(mode)
    b1.assert_approved_protocol(effective, v2.AUTHORIZED_PROTOCOL_SHA256)
    campaign = resolve_campaign_dir(out_dir, manifest_dir=manifest_dir, repo_root=repo_root)
    allowed = frozen_test_quarters(manifest_dir, effective)
    fitted = _assert_fitted_state(campaign)
    _assert_no_markers(campaign)
    resolved_model, _columns = model_feature_columns(effective, spec.model_id)

    frame = build_test_frame(
        effective=effective,
        split_map=spec.split_map,
        seed=spec.seed,
        allowed_quarters=allowed,
        windows_per_quarter=spec.windows_per_quarter,
        depths_ppm=spec.depths_ppm,
        geometry=spec.geometry,
        model_id=resolved_model,
    )

    campaign.mkdir(parents=True, exist_ok=True)
    # TOCTOU mitigation: re-validate the directory that actually exists before any marker or
    # trial file is written. A swap between validation and creation can leave at most an empty
    # directory behind; it cannot place a marker or a trial file inside protected evidence.
    resolve_campaign_dir(campaign, manifest_dir=manifest_dir, repo_root=repo_root)
    _assert_fitted_state(campaign)
    _assert_no_markers(campaign)

    model_id = fitted.get("model_id", resolved_model)
    test_access.claim_generation(
        campaign,
        {
            "generator": GENERATOR_NAME,
            "stage": "B2",
            "source": b2a.SOURCE,
            "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256,
            "protocol_version": effective["version"],
            "model_id": model_id,
            "window_days": float((spec.geometry or b2a.Geometry()).window_days),
            "test_quarters": sorted(spec.split_map),
        },
    )
    target = campaign / TRIALS_FILENAME
    frame.to_csv(target, index=False)
    test_access.complete_marker(
        campaign,
        test_access.MARKER_GENERATION,
        {"trials_rows": int(len(frame)), "trials_sha256": v2.sha256_file(target)},
    )
    digest = v2.sha256_file(target)
    return {
        "mode": MODE_SYNTHETIC,
        "generator": GENERATOR_NAME,
        "campaign_dir": str(campaign),
        "trials_path": str(target),
        "trials_sha256": digest,
        "trials_rows": int(len(frame)),
        "test_quarters": sorted(spec.split_map),
        "model_id": model_id,
    }
