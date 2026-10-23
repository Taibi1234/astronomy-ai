"""Phase 11 Stage B2a: synthetic fit-split trial builder (design §5.7).

Synthetic fixtures only. The builder generates its own time/flux arrays, runs the shared
detector (:func:`research.core.detect`) and the shared feature builder
(:mod:`research.features`), and returns train/validation rows with injected labels. It never
opens ``data/``, never reads a quarter CSV, never touches the frozen manifest tree, fits no
model, creates no campaign marker and reads no sealed trial.

The configuration comes from the authenticated B0 view (:func:`research.phase11_v2.
resolve_effective_protocol`); this module invents no second authority. Feature columns,
noise strata and the split vocabulary are all read from that view.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import transit_injection as ti

from . import core, phase11
from .features import FEATURE_NAMES, time_domain_features
from .phase11 import GateError
from .phase11_runner import resolve_output_dir

ROLE_NULL = "null_window"
ROLE_INJECTION = "injection"
FIT_SPLITS = ("train", "val")
SOURCE = "synthetic-fixture"
CADENCE_DAYS = 0.0204333
NOISE_PPM = 120.0
MIN_POINTS = 40
DETECTOR_COLUMNS = ("snr", "depth_est_ppm", "sigma_ppm")
NOISE_SCALE = {"observed": 1.0, "amplified_x2": 2.0}
METADATA_COLUMNS = (
    "trial_id",
    "quarter",
    "window_index",
    "split",
    "role",
    "requested_depth_ppm",
    "injected",
    "noise_condition",
    "source",
)
OUTPUT_FILENAME = "b2a_fit_split.csv"


# --- input validation --------------------------------------------------------


def _validate_split_map(split_map: object) -> dict[str, str]:
    """Refuse any test-split input before a single row is constructed."""
    if not isinstance(split_map, Mapping) or not split_map:
        raise GateError("split_map must be a non-empty mapping of quarter -> split")
    normalised: dict[str, str] = {}
    for quarter, split in split_map.items():
        if not isinstance(quarter, str) or not quarter:
            raise GateError("split_map keys must be non-empty quarter identifiers")
        if not isinstance(split, str):
            raise GateError(f"split for {quarter} is not a string: {split!r}")
        if split == "test":
            raise GateError(
                "B2a builds fit-split rows only; test-split input is refused before construction"
            )
        if split not in FIT_SPLITS:
            raise GateError(f"unsupported split {split!r}; allowed splits are {list(FIT_SPLITS)}")
        normalised[quarter] = split
    missing = [split for split in FIT_SPLITS if split not in normalised.values()]
    if missing:
        raise GateError(f"split_map must populate every fit split; missing {missing}")
    return normalised


def _validate_effective(effective: object, model_id: str | None) -> tuple[str, list[str]]:
    """Read feature columns and strata from the B0 view; refuse anything uncomputable."""
    if not isinstance(effective, Mapping):
        raise GateError("effective protocol must be a mapping produced by B0")
    features_block = effective.get("features")
    if not isinstance(features_block, Mapping):
        raise GateError("effective protocol has no features block")
    if model_id is None:
        model_id = features_block.get("primary_model")
    if not isinstance(model_id, str) or not model_id:
        raise GateError("effective protocol names no primary_model; pass model_id explicitly")
    columns = phase11.feature_columns(dict(effective), model_id)
    declared_detector = set(features_block.get("detector_outputs") or ())
    declared_flux = set(features_block.get("flux_features") or ())
    unbuildable = sorted(declared_detector - set(DETECTOR_COLUMNS))
    unbuildable += sorted(declared_flux - set(FEATURE_NAMES))
    if unbuildable:
        raise GateError(f"B2a cannot produce the declared feature columns {unbuildable}")
    unknown = sorted(set(columns) - (set(DETECTOR_COLUMNS) | set(FEATURE_NAMES)))
    if unknown:
        raise GateError(f"B2a cannot produce the requested feature columns {unknown}")
    return model_id, columns


def validate_conditions(effective: Mapping) -> list[str]:
    injection = effective.get("injection")
    if not isinstance(injection, Mapping):
        raise GateError("effective protocol has no injection block")
    conditions = injection.get("noise_conditions")
    if not isinstance(conditions, list) or not conditions:
        raise GateError("effective protocol has no non-empty injection.noise_conditions")
    unknown = [condition for condition in conditions if condition not in NOISE_SCALE]
    if unknown:
        raise GateError(f"unsupported noise conditions: {unknown}")
    if any(not isinstance(condition, str) or not condition for condition in conditions):
        raise GateError("noise conditions must be non-empty strings")
    return list(conditions)


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


@dataclass(frozen=True)
class Geometry:
    """Window sampling geometry; constants unless a test or the caller overrides them."""

    window_days: float = 5.0
    cadence_days: float = CADENCE_DAYS
    mission: str = "kepler"
    noise_ppm: float = NOISE_PPM


def _validate_geometry(seed: object, windows_per_quarter: object, geometry: Geometry) -> None:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise GateError("seed must be an integer")
    if (
        isinstance(windows_per_quarter, bool)
        or not isinstance(windows_per_quarter, int)
        or windows_per_quarter < 1
    ):
        raise GateError("windows_per_quarter must be a positive integer")
    if not isinstance(geometry, Geometry):
        raise GateError("geometry must be a phase11_b2a.Geometry instance")
    if not np.isfinite(geometry.window_days) or geometry.window_days <= 0:
        raise GateError("window_days must be finite and positive")
    if not np.isfinite(geometry.cadence_days) or geometry.cadence_days <= 0:
        raise GateError("cadence_days must be finite and positive")
    if geometry.window_days / geometry.cadence_days < MIN_POINTS:
        raise GateError(
            f"a {geometry.window_days}-day window at {geometry.cadence_days}-day cadence "
            f"holds fewer than {MIN_POINTS} cadences"
        )
    if geometry.mission not in ti.BJD_REFERENCE:
        raise GateError(f"unknown mission {geometry.mission!r}; known: {sorted(ti.BJD_REFERENCE)}")
    if not np.isfinite(geometry.noise_ppm) or geometry.noise_ppm <= 0:
        raise GateError("noise_ppm must be finite and positive")


# --- synthetic arrays --------------------------------------------------------


def synthetic_window(
    *,
    window_days: float,
    cadence_days: float,
    noise_condition: str,
    requested_depth_ppm: float,
    rng: np.random.Generator,
    mission: str = "kepler",
    noise_ppm: float = NOISE_PPM,
    delta_days: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic synthetic (times, flux) for one window.

    Times sit on a contiguous cadence grid around an ephemeris-crossing start; injected windows
    receive a coherent transit at every orbit, exactly as the campaign does. The depth is used
    only to build the flux: it is never passed to the detector. When ``delta_days`` is supplied
    the caller owns the phase offset (the test generator records it as ground truth); otherwise
    one is drawn from ``rng``.
    """
    if noise_condition not in NOISE_SCALE:
        raise GateError(f"unknown noise condition {noise_condition!r}")
    epochs = int(round(window_days / cadence_days))
    if epochs < MIN_POINTS:
        raise GateError("synthetic window holds too few cadences")
    reference = ti.BJD_REFERENCE[mission]
    epoch_days = ti.TRANSIT_EPOCH_BJD_TDB - reference
    start = epoch_days + int(rng.integers(0, 12)) * ti.PERIOD_DAYS - window_days / 2.0
    times = start + np.arange(epochs) * cadence_days
    scale = NOISE_SCALE[noise_condition]
    flux = 1.0 + rng.normal(0.0, noise_ppm * 1e-6 * scale, epochs)
    if requested_depth_ppm > 0:
        delta = float(rng.uniform(-0.15, 0.15)) if delta_days is None else float(delta_days)
        phase = core.phase_offsets(times, mission, delta)
        flux = ti.inject_transit(flux, phase, float(requested_depth_ppm))
    keep = np.ones(epochs, dtype=bool)
    lo = epochs // 4
    keep[lo : lo + max(3, epochs // 12)] = False
    return times[keep], flux[keep]


def detect_window(times: np.ndarray, flux: np.ndarray, mission: str) -> dict:
    """Call the shared detector with times, flux and mission only — never depth or truth."""
    return core.detect(times, flux, mission)


# --- frame assembly ----------------------------------------------------------


def _row(
    *,
    quarter: str,
    window_index: int,
    split: str,
    noise_condition: str,
    requested_depth_ppm: float,
    times: np.ndarray,
    flux: np.ndarray,
    mission: str,
) -> dict:
    detection = detect_window(times, flux, mission)
    role = ROLE_NULL if requested_depth_ppm == 0 else ROLE_INJECTION
    return {
        "trial_id": f"{quarter}-{window_index}-d{int(requested_depth_ppm)}-{noise_condition}",
        "quarter": quarter,
        "window_index": int(window_index),
        "split": split,
        "role": role,
        "requested_depth_ppm": float(requested_depth_ppm),
        "injected": bool(requested_depth_ppm > 0),
        "noise_condition": noise_condition,
        "source": SOURCE,
        "snr": float(detection["snr"]),
        "depth_est_ppm": float(detection["depth_ppm"]),
        "sigma_ppm": float(detection["sigma_ppm"]),
        **time_domain_features(times, flux),
    }


def _assert_label_invariant(frame: pd.DataFrame) -> None:
    expected = frame["requested_depth_ppm"] > 0
    if not bool((frame["injected"] == expected).all()):
        raise GateError("label invariant violated: injected != (requested_depth_ppm > 0)")
    nulls = frame[frame["role"] == ROLE_NULL]
    if bool(nulls["injected"].any()) or bool((nulls["requested_depth_ppm"] != 0).any()):
        raise GateError("null windows must be injected=False with requested_depth_ppm=0")


def _assert_null_windows(frame: pd.DataFrame) -> None:
    present = set(frame["split"].unique())
    if "test" in present:
        raise GateError("B2a frame must never contain test-split rows")
    missing = sorted(set(FIT_SPLITS) - present)
    if missing:
        raise GateError(f"frame is missing fit splits: {missing}")
    for split in FIT_SPLITS:
        nulls = frame[(frame["split"] == split) & (frame["role"] == ROLE_NULL)]
        if nulls.empty:
            raise GateError(f"split {split!r} has no null windows; calibration would fail")


def build_fit_split_frame(
    *,
    effective: Mapping,
    split_map: Mapping[str, str],
    seed: int,
    windows_per_quarter: int = 1,
    depths_ppm: Sequence[float] = (150.0, 300.0),
    geometry: Geometry | None = None,
    model_id: str | None = None,
) -> pd.DataFrame:
    """Build synthetic train/validation rows for B1. Fits nothing and writes nothing."""
    geometry = Geometry() if geometry is None else geometry
    splits = _validate_split_map(split_map)
    _, columns = _validate_effective(effective, model_id)
    conditions = validate_conditions(effective)
    depths = _validate_depths(depths_ppm)
    _validate_geometry(seed, windows_per_quarter, geometry)

    rng = np.random.default_rng(seed)
    rows = []
    for quarter in sorted(splits):
        for window_index in range(windows_per_quarter):
            for noise_condition in conditions:
                for depth in (0.0, *depths):
                    times, flux = synthetic_window(
                        window_days=float(geometry.window_days),
                        cadence_days=float(geometry.cadence_days),
                        noise_condition=noise_condition,
                        requested_depth_ppm=float(depth),
                        rng=rng,
                        mission=geometry.mission,
                        noise_ppm=float(geometry.noise_ppm),
                    )
                    rows.append(
                        _row(
                            quarter=quarter,
                            window_index=window_index,
                            split=splits[quarter],
                            noise_condition=noise_condition,
                            requested_depth_ppm=float(depth),
                            times=times,
                            flux=flux,
                            mission=geometry.mission,
                        )
                    )

    frame = pd.DataFrame(rows)
    _assert_label_invariant(frame)
    _assert_null_windows(frame)
    phase11.assert_fit_splits(frame, effective)

    missing = [column for column in (*columns, *METADATA_COLUMNS) if column not in frame.columns]
    if missing:
        raise GateError(f"builder frame is missing required columns {missing}")
    return frame


def write_fit_split_csv(
    frame: pd.DataFrame,
    out_dir: Path,
    *,
    manifest_dir: Path,
    repo_root: Path,
) -> Path:
    """Write the frame under an isolated directory; refuse protected or frozen destinations."""
    resolved = resolve_output_dir(Path(out_dir), manifest_dir=manifest_dir, repo_root=repo_root)
    resolved.mkdir(parents=True, exist_ok=True)
    resolve_output_dir(resolved, manifest_dir=manifest_dir, repo_root=repo_root)
    target = resolved / OUTPUT_FILENAME
    frame.to_csv(target, index=False)
    return target
