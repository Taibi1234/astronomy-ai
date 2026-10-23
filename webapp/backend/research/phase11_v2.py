"""Phase 11 Stage 2 hardening: protocol v2.3 loading, thresholds, markers, comparison.

This module implements the rules frozen in ``reports/phase11_generalization/
protocol_v2_3.json`` (SHA-256 ``e1dc5cc9...``). It never imports campaign data, never
reads a seeded test row, and never runs a campaign; every function here either validates
state or computes from caller-supplied synthetic or already-authorized rows.

Deliberate non-goals
--------------------
* The v1 code path in ``phase11.py`` is untouched, so the historical smoke artifacts stay
  reproducible and no previously verified behaviour changes.
* No CLI, no fitting, no evaluation entry point is added here.
* The minimum meaningful difference is ``None`` by owner decision D1: :func:`paired_comparison`
  can therefore never return a practical-superiority verdict.
"""

from __future__ import annotations

import copy
import json
import pickle
import re
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from scipy.stats import norm

from .phase11 import (
    SAFE_MODEL_FILENAME,
    GateError,
    _safe_model_filename,
    assert_fit_splits,
    load_frozen_json,
    require_noise_strata,
    sha256_bytes,
    sha256_file,
    wilson_interval,
    write_json_with_sidecar,
)
from .test_access import (
    MARKER_ACCESS,
    MARKER_GENERATION,
    MARKERS,
    assert_no_markers,
    begin_marker,
    complete_marker,
    marker_state,
)

# --- authorized protocol identity -------------------------------------------

AUTHORIZED_PROTOCOL_NAME = "protocol_v2_3.json"
AUTHORIZED_PROTOCOL_SHA256 = "e1dc5cc9ed4e6e2dc4645a82efc4f7638fb0f3128248b9810c67ba339f32c154"
AUTHORIZED_PROTOCOL_VERSION = "phase11b-protocol-v2.3-proposal"
PROTOCOL_SCHEMA_VERSION = 2
PROTOCOL_PHASE = "11b"
MANIFEST_PHASE = "11a"
FITTED_SCHEMA_VERSION = 2

# B0: the frozen v1 protocol is the inherited-configuration source; the frozen experiment
# config is the separately bound source of ``injection.noise_conditions``. Both are pinned,
# and the config's hash is taken from the authenticated v2.3 manifest at run time.
V1_PROTOCOL_NAME = "protocol.json"
V1_PROTOCOL_SHA256 = "ded2bd5eea3cfb3cbd5af0b67e439a767584b9bf508f02afe2a4b5d56a75319f"
V1_PROTOCOL_SCHEMA_VERSION = 1
EXPERIMENT_CONFIG_NAME = "experiment_config.json"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
INHERITED_BLOCKS = {
    "features": ("features",),
    "preprocessing": ("preprocessing",),
    "models": ("models",),
    "seeds": ("seeds",),
    "campaign_modes": ("campaign", "modes"),
    "campaign_order": ("campaign", "order"),
}
INHERITED_PROSE_KEYS = frozenset({"rule", "note"})
REQUIRED_EFFECTIVE_KEYS = (
    "features.sets",
    "features.forbidden",
    "features.detector_outputs",
    "features.flux_features",
    "preprocessing.fit_splits",
    "injection.noise_conditions",
    "models.logistic_regression",
    "models.random_forest",
    "models.dummy",
    "thresholds.target_fpr",
    "thresholds.min_calibration_n_per_stratum",
    "thresholds.detector.floor_snr",
    "thresholds.fitted_models.floor_snr",
)

TARGET_FPR = 0.05
MIN_CALIBRATION_N = 30
MISMATCH_TOLERANCE = 0.02
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261024
INTERVAL_ALPHA = 0.05
TIMING_TOLERANCE_DAYS = 0.0377
MINIMUM_MEANINGFUL_DIFFERENCE: float | None = None

# Marker names and states are owned by ``research/test_access`` and re-exported above.

REQUIRED_PROTOCOL_SECTIONS = (
    "phase",
    "schema_version",
    "version",
    "supersedes",
    "approval_decisions",
    "data_roles",
    "detection",
    "thresholds",
    "reporting",
    "fpr",
    "comparison",
    "bootstrap",
    "insufficient_data",
    "test_access",
    "provenance",
    "frozen_inputs",
)

MANIFEST_STRUCTURE = {
    "split.json": ("phase", "unit_of_independence", "quotas", "assignment", "quarters"),
    "windows_primary.json": ("phase", "window_days", "rules", "windows"),
    "windows_sensitivity.json": ("phase", "window_days", "rules", "windows"),
    "null_library.json": ("primary", "sensitivity"),
    "experiment_config.json": (
        "phase",
        "target",
        "unit_of_independence",
        "split",
        "window",
        "injection",
        "ml_ladder",
        "metrics",
    ),
}
MANIFEST_NAMES = tuple(MANIFEST_STRUCTURE)
WINDOW_MANIFESTS = {
    "windows_primary.json": 5.0,
    "windows_sensitivity.json": 3.0,
}
# null_library.json carries no phase header; every other manifest declares one.
PHASELESS_MANIFESTS = ("null_library.json",)
WINDOW_REQUIRED_KEYS = ("quarter", "split", "role", "window_index", "start_index", "end_index")


# --- protocol loading and validation ----------------------------------------


def _read_sidecar(path: Path) -> str:
    sidecar = path.with_name(path.name.replace(".json", ".sha256"))
    if not sidecar.is_file():
        raise GateError(f"missing hash sidecar for {path.name}")
    token = sidecar.read_text(encoding="utf-8").split()
    if not token:
        raise GateError(f"empty hash sidecar for {path.name}")
    return token[0]


def load_protocol_v21(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> tuple[dict, str]:
    """Load the authorized v2.3 protocol or refuse.

    Four independent checks must all pass: the raw bytes match the sidecar, the raw bytes
    match the authorized constant, the header matches phase/schema/version, and the body
    contains every required section. A passing hash alone is never treated as proof of
    content, which is why the invariants below are re-checked on every load.
    """
    pin = AUTHORIZED_PROTOCOL_SHA256 if expected_sha256 is None else expected_sha256
    if not path.is_file():
        raise GateError(f"protocol not found: {path}")
    raw = path.read_bytes()
    digest = sha256_bytes(raw)
    if _read_sidecar(path) != digest:
        raise GateError(f"{path.name} does not match its recorded hash")
    if digest != pin:
        raise GateError(f"{path.name} hash {digest} is not the authorized protocol {pin}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"{path.name} is not readable JSON") from exc

    if payload.get("phase") != PROTOCOL_PHASE:
        raise GateError(f"protocol phase {payload.get('phase')!r} != {PROTOCOL_PHASE!r}")
    if payload.get("schema_version") != PROTOCOL_SCHEMA_VERSION:
        raise GateError(
            f"protocol schema_version {payload.get('schema_version')!r} "
            f"!= {PROTOCOL_SCHEMA_VERSION!r}"
        )
    if payload.get("version") != AUTHORIZED_PROTOCOL_VERSION:
        raise GateError(f"protocol version {payload.get('version')!r} is not authorized")
    missing = [key for key in REQUIRED_PROTOCOL_SECTIONS if key not in payload]
    if missing:
        raise GateError(f"protocol is missing required sections: {missing}")
    if not isinstance(payload["frozen_inputs"], dict) or not isinstance(
        payload["frozen_inputs"].get("files"), dict
    ):
        raise GateError("protocol must bind frozen_inputs.files as a mapping")

    _assert_threshold_invariants(payload)
    _assert_detection_invariants(payload)
    _assert_decision_invariants(payload)
    return payload, digest


def _assert_threshold_invariants(payload: dict) -> None:
    thresholds = payload["thresholds"]
    if float(thresholds["target_fpr"]) != TARGET_FPR:
        raise GateError(f"target_fpr must be {TARGET_FPR}, got {thresholds['target_fpr']}")
    if int(thresholds["min_calibration_n_per_stratum"]) != MIN_CALIBRATION_N:
        raise GateError(
            f"min_calibration_n_per_stratum must be {MIN_CALIBRATION_N}, "
            f"got {thresholds['min_calibration_n_per_stratum']}"
        )
    if payload["reporting"]["primary_family"].find("noise_condition") < 0:
        raise GateError("primary reporting must remain per noise stratum")


def _assert_detection_invariants(payload: dict) -> None:
    detection = payload["detection"]
    if detection["comparison_operator"].strip() != "strict >":
        raise GateError("only the pre-registered strict '>' comparison is authorized")
    tolerance = payload["approval_decisions"]["D2_timing_tolerance_days"]["value"]
    if float(tolerance) != TIMING_TOLERANCE_DAYS:
        raise GateError(
            f"timing tolerance must remain {TIMING_TOLERANCE_DAYS} days, got {tolerance}"
        )
    if str(TIMING_TOLERANCE_DAYS) not in detection.get("timing_qualified_recovery", ""):
        raise GateError("the recovery rule must state the 0.0377-day tolerance")


def _assert_decision_invariants(payload: dict) -> None:
    if payload["data_roles"]["l7_calibration"].find("val") < 0:
        raise GateError("L7 calibration must remain validation-only")
    if payload["bootstrap"]["method_primary"] != "percentile":
        raise GateError("percentile bootstrap must remain the primary interval method")
    decision = payload["approval_decisions"]["D1_minimum_meaningful_difference"]
    if decision["value"] is not None:
        raise GateError("the minimum meaningful difference must remain unset (D1)")
    declared = set(payload["test_access"]["markers"])
    missing = [name for name in MARKERS if name not in declared]
    if missing:
        raise GateError(f"test_access markers must include {missing}")


def validate_manifests(manifest_dir: Path, protocol: dict) -> dict[str, str]:
    """Verify every frozen manifest against the protocol, by hash, phase and structure."""
    frozen = protocol["frozen_inputs"]["files"]
    hashes = {name: _validate_manifest_file(manifest_dir, name, frozen) for name in MANIFEST_NAMES}
    _validate_window_manifests(manifest_dir)
    return hashes


def _validate_manifest_file(manifest_dir: Path, name: str, frozen: dict) -> str:
    path = manifest_dir / name
    if not path.is_file():
        raise GateError(f"missing manifest: {name}")
    digest = sha256_file(path)
    expected = frozen.get(name)
    if expected is None:
        raise GateError(f"protocol does not bind {name}")
    if digest != expected:
        raise GateError(f"{name} hash {digest} does not match the protocol")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if name not in PHASELESS_MANIFESTS and payload.get("phase") != MANIFEST_PHASE:
        raise GateError(f"{name} phase {payload.get('phase')!r} != {MANIFEST_PHASE!r}")
    if name in PHASELESS_MANIFESTS and "phase" in payload:
        if payload["phase"] != MANIFEST_PHASE:
            raise GateError(f"{name} phase {payload['phase']!r} != {MANIFEST_PHASE!r}")
    missing = [key for key in MANIFEST_STRUCTURE[name] if key not in payload]
    if missing:
        raise GateError(f"{name} is missing required keys: {missing}")
    return digest


def _validate_window_manifests(manifest_dir: Path) -> None:
    for name, days in WINDOW_MANIFESTS.items():
        payload = json.loads((manifest_dir / name).read_text(encoding="utf-8"))
        if float(payload["window_days"]) != days:
            raise GateError(f"{name} must carry the {days}-day window length")
        for record in payload["windows"]:
            missing = [key for key in WINDOW_REQUIRED_KEYS if key not in record]
            if missing:
                raise GateError(f"{name} window record is missing {missing}")


def load_frozen_offsets(manifest_dir: Path, protocol: dict) -> tuple[dict, str]:
    path = manifest_dir / "offsets.json"
    if not path.is_file():
        raise GateError("missing offsets.json")
    digest = sha256_file(path)
    if digest != protocol["frozen_inputs"]["files"].get("offsets.json"):
        raise GateError("offsets.json does not match the protocol")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("phase") != PROTOCOL_PHASE:
        raise GateError(f"offsets phase {payload.get('phase')!r} != {PROTOCOL_PHASE!r}")
    return payload, digest


# --- B0: effective protocol resolution ---------------------------------------


def validate_manifest_entry(protocol: dict) -> str:
    """Return the authenticated ``experiment_config.json`` hash from the v2.3 manifest."""
    frozen = protocol.get("frozen_inputs")
    if not isinstance(frozen, dict):
        raise GateError("protocol has no frozen_inputs mapping")
    files = frozen.get("files")
    if not isinstance(files, dict):
        raise GateError("protocol frozen_inputs has no files mapping")
    if EXPERIMENT_CONFIG_NAME not in files:
        raise GateError(f"manifest has no entry for {EXPERIMENT_CONFIG_NAME}")
    entry = files[EXPERIMENT_CONFIG_NAME]
    if not isinstance(entry, str):
        raise GateError(f"manifest entry for {EXPERIMENT_CONFIG_NAME} is not a string")
    if SHA256_PATTERN.fullmatch(entry) is None:
        raise GateError(
            f"manifest entry for {EXPERIMENT_CONFIG_NAME} is not 64 lowercase hex characters"
        )
    return entry


def load_experiment_config(path: Path, *, expected_sha256: str) -> tuple[dict, str]:
    """Hash the exact bytes, compare with the manifest entry, and only then parse."""
    path = Path(path)
    if not path.is_file():
        raise GateError(f"experiment config not found: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GateError(f"experiment config is unreadable: {exc}") from exc
    digest = sha256_bytes(raw)
    if digest != expected_sha256:
        raise GateError(
            f"{path.name} hash {digest} does not match the authenticated manifest entry "
            f"{expected_sha256}"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"{path.name} is not readable JSON") from exc
    return payload, digest


def _extract_noise_conditions(config: dict) -> list[str]:
    """Validate the config structure and return the only permitted copied value."""
    if not isinstance(config, dict):
        raise GateError("experiment config must be a JSON object")
    injection = config.get("injection")
    if not isinstance(injection, dict):
        raise GateError("experiment config has no injection mapping")
    noise = injection.get("noise_conditions")
    if not isinstance(noise, list) or not noise:
        raise GateError("experiment config has no non-empty noise_conditions list")
    if any(not isinstance(value, str) or not value for value in noise):
        raise GateError("experiment config noise_conditions must be non-empty strings")
    return [str(value) for value in noise]


def _require_path(document: dict, dotted: str) -> None:
    node: object = document
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise GateError(f"effective protocol is missing required key {dotted!r}")
        node = node[part]


def _copy_block(source: dict, path: tuple[str, ...]) -> object:
    node: object = source
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise GateError(f"v1 protocol is missing inherited block {'/'.join(path)}")
        node = node[key]
    return copy.deepcopy(node)


def load_protocol_v1(
    path: Path,
    *,
    expected_sha256: str = V1_PROTOCOL_SHA256,
) -> tuple[dict, str]:
    """Load the pinned v1 protocol: present, readable, sidecar-consistent and hash-pinned."""
    path = Path(path)
    if not path.is_file():
        raise GateError(f"v1 protocol not found: {path}")
    payload, digest = load_frozen_json(
        path,
        expected_phase=PROTOCOL_PHASE,
        expected_schema=V1_PROTOCOL_SCHEMA_VERSION,
    )
    if digest != expected_sha256:
        raise GateError(
            f"{path.name} hash {digest} is not the pinned v1 protocol {expected_sha256}"
        )
    return payload, digest


def _authenticate_sources(
    protocol_v2_3: dict,
    protocol_v2_3_sha256: str,
    protocol_v1_sha256: str,
    experiment_config_sha256: str,
) -> None:
    """Re-check all three supplied digests against the pins before any merge happens."""
    if protocol_v2_3_sha256 != AUTHORIZED_PROTOCOL_SHA256:
        raise GateError(
            f"v2.3 digest {protocol_v2_3_sha256} is not the authorized protocol "
            f"{AUTHORIZED_PROTOCOL_SHA256}"
        )
    if protocol_v1_sha256 != V1_PROTOCOL_SHA256:
        raise GateError(f"v1 digest {protocol_v1_sha256} is not the pinned v1 protocol")
    manifest_entry = validate_manifest_entry(protocol_v2_3)
    if experiment_config_sha256 != manifest_entry:
        raise GateError(
            f"experiment config digest {experiment_config_sha256} is not the authenticated "
            f"manifest entry {manifest_entry}"
        )


def _declared_inherited_blocks(protocol_v2_3: dict) -> set[str]:
    """Return the whitelisted block names the protocol declares; refuse anything else."""
    inherited = protocol_v2_3.get("inherits_from_v1")
    if not isinstance(inherited, dict):
        raise GateError("v2.3 protocol has no inherits_from_v1 mapping")
    declared = set(inherited) - INHERITED_PROSE_KEYS
    unknown = sorted(declared - set(INHERITED_BLOCKS))
    if unknown:
        raise GateError(f"unsupported inherits_from_v1 keys: {unknown}")
    missing = sorted(set(INHERITED_BLOCKS) - declared)
    if missing:
        raise GateError(f"inherits_from_v1 is missing required blocks: {missing}")
    return declared


def _threshold_floors(protocol_v2_3: dict) -> tuple[object, object]:
    """Return (detector, l7) floors as declared by v2.3, before any compatibility mapping."""
    thresholds = protocol_v2_3.get("thresholds")
    if not isinstance(thresholds, dict):
        raise GateError("v2.3 protocol has no thresholds block")
    for key in ("floor_snr_detector", "floor_snr_l7"):
        if key not in thresholds:
            raise GateError(f"v2.3 thresholds block is missing {key!r}")
    return thresholds["floor_snr_detector"], thresholds["floor_snr_l7"]


def effective_protocol(
    protocol_v2_3: dict,
    protocol_v2_3_sha256: str,
    protocol_v1: dict,
    protocol_v1_sha256: str,
    experiment_config: dict,
    experiment_config_sha256: str,
) -> dict:
    """Pure merge of the authenticated v2.3, v1 and experiment-config values.

    No file I/O: every argument is already authenticated, and the supplied digests are
    re-checked against the pins. Configuration only — it reads no trial data and grants no
    execution authority.
    """
    _authenticate_sources(
        protocol_v2_3, protocol_v2_3_sha256, protocol_v1_sha256, experiment_config_sha256
    )
    _declared_inherited_blocks(protocol_v2_3)
    detector_floor, l7_floor = _threshold_floors(protocol_v2_3)
    noise = _extract_noise_conditions(experiment_config)

    effective = copy.deepcopy(protocol_v2_3)
    for name, source_path in INHERITED_BLOCKS.items():
        value = _copy_block(protocol_v1, source_path)
        if name.startswith("campaign_"):
            effective.setdefault("campaign", {})[name.split("_", 1)[1]] = value
        else:
            effective[name] = value
    effective["injection"] = {"noise_conditions": noise}
    effective["thresholds"]["detector"] = {"floor_snr": detector_floor}
    effective["thresholds"]["fitted_models"] = {"floor_snr": l7_floor}

    for dotted in REQUIRED_EFFECTIVE_KEYS:
        _require_path(effective, dotted)
    return effective


def resolve_effective_protocol(
    manifest_dir: Path,
    *,
    protocol_path: Path | None = None,
    v1_path: Path | None = None,
    experiment_config_path: Path | None = None,
) -> tuple[dict, dict]:
    """File-level B0 entry point: authenticate the triple, then return (effective, provenance)."""
    manifest_dir = Path(manifest_dir)
    v23_path = Path(protocol_path) if protocol_path else manifest_dir / AUTHORIZED_PROTOCOL_NAME
    v1_file = Path(v1_path) if v1_path else manifest_dir / V1_PROTOCOL_NAME
    config_path = (
        Path(experiment_config_path)
        if experiment_config_path
        else manifest_dir / EXPERIMENT_CONFIG_NAME
    )

    protocol_v2_3, v23_hash = load_protocol_v21(v23_path)
    manifest_entry = validate_manifest_entry(protocol_v2_3)
    experiment_config, config_hash = load_experiment_config(
        config_path, expected_sha256=manifest_entry
    )
    protocol_v1, v1_hash = load_protocol_v1(v1_file)

    effective = effective_protocol(
        protocol_v2_3,
        v23_hash,
        protocol_v1,
        v1_hash,
        experiment_config,
        config_hash,
    )
    provenance = {
        "protocol_v2_3": {
            "path": str(v23_path),
            "sha256": v23_hash,
            "version": protocol_v2_3["version"],
        },
        "protocol_v1": {"path": str(v1_file), "sha256": v1_hash},
        "experiment_config": {
            "path": str(config_path),
            "sha256": config_hash,
            "manifest_entry": manifest_entry,
        },
        "inherited_blocks": list(INHERITED_BLOCKS),
        "copied_from_experiment_config": ["injection.noise_conditions"],
        "derived_floors": {
            "detector": effective["thresholds"]["detector"]["floor_snr"],
            "l7": effective["thresholds"]["fitted_models"]["floor_snr"],
        },
        "grants_execution_authority": False,
    }
    return effective, provenance


# --- v2.1 threshold algorithm -----------------------------------------------


def exceedance(values: np.ndarray, threshold: float) -> float:
    """Calibration exceedance under the strict '>' rule."""
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        raise GateError("cannot compute exceedance on an empty calibration set")
    return float(np.mean(values > float(threshold)))


def choose_threshold_v21(
    scores: Sequence[float] | np.ndarray,
    *,
    scope: str,
    target_fpr: float = TARGET_FPR,
    floor: float | None = None,
    min_n: int = MIN_CALIBRATION_N,
    score_supremum: float | None = None,
) -> dict:
    """The frozen v2.1 rule: min candidate at or above t0 whose exceedance is <= target.

    The candidate set includes ``t0`` itself, so the interpolated quantile can win; that is
    the defect this rule was written to fix in v1. Ties are absorbed by the strict '>'
    counting rule, and a tie can never make the constraint unsatisfiable because
    ``e(max(score)) == 0``.
    """
    values = np.asarray(scores, dtype=float)
    values = values[np.isfinite(values)]
    n = int(values.size)
    if n < int(min_n):
        raise GateError(f"{scope}: {n} finite calibration scores is below the minimum of {min_n}")
    if not 0.0 < target_fpr < 1.0:
        raise GateError(f"target_fpr must be in (0, 1), got {target_fpr}")
    if floor is not None and not np.isfinite(float(floor)):
        raise GateError(f"{scope}: floor must be finite, got {floor!r}")

    quantile = float(np.percentile(values, 100.0 * (1.0 - target_fpr), method="linear"))
    floor_binding = floor is not None and float(floor) > quantile
    t0 = float(floor) if floor_binding else quantile
    threshold = _first_acceptable(values, t0, target_fpr)
    if threshold is None:  # unreachable by construction: e(max) == 0 <= target
        raise GateError(f"{scope}: no candidate satisfies the exceedance target")

    if threshold > t0:
        source = "tie_lift"
    elif floor_binding:
        source = "floor"
    else:
        source = "quantile"

    observed = exceedance(values, threshold)
    if observed > target_fpr:
        raise GateError(f"{scope}: calibration exceedance {observed} exceeds {target_fpr}")
    degenerate = score_supremum is not None and threshold >= float(score_supremum)

    return {
        "threshold": threshold,
        "threshold_source": source,
        "quantile_q": quantile,
        "t0": t0,
        "floor": floor,
        "floor_binding": bool(floor_binding),
        "n": n,
        "calibration_exceedance": observed,
        "target_fpr": float(target_fpr),
        "scope": scope,
        "comparison": ">",
        "percentile_method": "linear",
        "threshold_degenerate": bool(degenerate),
        "distinct_scores": int(np.unique(values).size),
    }


def _first_acceptable(values: np.ndarray, t0: float, target_fpr: float) -> float | None:
    """Smallest candidate at or above t0 whose strict exceedance is within target."""
    candidates = np.unique(np.concatenate(([t0], values[values >= t0])))
    for candidate in candidates:
        if exceedance(values, float(candidate)) <= target_fpr:
            return float(candidate)
    return None


def calibrate_thresholds_v21(
    frame: pd.DataFrame,
    protocol: dict,
    *,
    score_column: str,
    splits: Iterable[str],
    role: str,
    floor: float | None,
    score_supremum: float | None,
    context: str,
) -> dict[str, dict]:
    """Calibrate one threshold per declared noise stratum; fail closed on any gap."""
    allowed = {str(split) for split in splits}
    if "test" in allowed:
        raise GateError(f"{context}: test rows may never be used for calibration")
    for column in (score_column, "split", "role", "noise_condition"):
        if column not in frame.columns:
            raise GateError(f"{context}: frame needs a {column!r} column")

    present_splits = {str(value) for value in frame["split"].unique()}
    if "test" in present_splits:
        raise GateError(f"{context}: test rows may never be used for calibration")
    if not present_splits <= allowed:
        raise GateError(f"{context}: unexpected splits {sorted(present_splits - allowed)}")

    calibration = frame[frame["role"] == role]
    if calibration.empty:
        raise GateError(f"{context}: no {role!r} rows to calibrate on")
    declared = protocol["injection"]["noise_conditions"]
    require_noise_strata(calibration["noise_condition"].unique(), declared, context=context)

    thresholds: dict[str, dict] = {}
    for noise, group in calibration.groupby("noise_condition"):
        key = str(noise)
        if key not in {str(value) for value in declared}:
            raise GateError(f"{context}: undeclared noise stratum {key!r}")
        thresholds[key] = choose_threshold_v21(
            group[score_column].to_numpy(dtype=float),
            scope=f"{context}|{key}",
            target_fpr=float(protocol["thresholds"]["target_fpr"]),
            floor=floor,
            min_n=int(protocol["thresholds"]["min_calibration_n_per_stratum"]),
            score_supremum=score_supremum,
        )
    return thresholds


def assert_strata_operative(thresholds: dict[str, dict]) -> None:
    """Operability gate: a degenerate threshold has no usable operating point."""
    degenerate = sorted(
        key for key, entry in thresholds.items() if entry.get("threshold_degenerate")
    )
    if degenerate:
        raise GateError(
            f"degenerate thresholds at the top of the score range: {degenerate}; "
            "no operative operating point exists for these strata"
        )


def stratum_table(thresholds: dict[str, dict]) -> dict:
    """Compact, hashable provenance summary of a calibration result."""
    return {
        key: {
            "threshold": entry["threshold"],
            "threshold_source": entry["threshold_source"],
            "n": entry["n"],
            "calibration_exceedance": entry["calibration_exceedance"],
            "floor_binding": entry["floor_binding"],
            "threshold_degenerate": entry["threshold_degenerate"],
            "distinct_scores": entry["distinct_scores"],
        }
        for key, entry in sorted(thresholds.items())
    }


def detector_table(thresholds: dict[str, dict]) -> dict:
    """Compact, hashable view of the per-stratum physics-detector thresholds.

    B1's fitted payload carries this beside the L7 table so the test evaluator never has to
    calibrate the comparator from test data (protocol ``test_controls_excluded``).
    """
    if not isinstance(thresholds, dict) or not thresholds:
        raise GateError("detector thresholds must be a non-empty mapping of stratum -> entry")
    table = {}
    for key, entry in sorted(thresholds.items()):
        if not isinstance(entry, dict) or "threshold" not in entry:
            raise GateError(f"detector threshold entry for {key!r} has no threshold value")
        value = float(entry["threshold"])
        if not np.isfinite(value):
            raise GateError(f"detector threshold for {key!r} is not finite")
        table[str(key)] = {
            "threshold": value,
            "floor": None if entry.get("floor") is None else float(entry["floor"]),
            "floor_applied": bool(entry.get("floor_applied", False)),
            "n": int(entry.get("n", 0)),
            "calibration_exceedance": float(entry.get("calibration_exceedance", 0.0)),
            "target_fpr": float(entry.get("target_fpr", TARGET_FPR)),
            "scope": str(entry.get("scope", key)),
            "percentile_method": str(entry.get("percentile_method", "linear")),
            "comparison": str(entry.get("comparison", ">")),
        }
    return table


# --- atomic, one-way markers ------------------------------------------------
#
# Implemented once in ``research/test_access`` and re-exported at the top of this module,
# so the legacy v1 evaluator and this v2 path cannot drift apart.


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --- provenance -------------------------------------------------------------


def _git(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:  # git missing, or repo_root does not exist
        raise GateError(f"git is unavailable for {repo_root}: {exc}") from exc
    if result.returncode != 0:
        raise GateError(f"git {' '.join(args)} failed: {result.stderr.strip()[:200]}")
    return result.stdout.strip()


def git_provenance(repo_root: Path) -> dict:
    """Commit id, branch and tracked-tree dirtiness. Fails closed if git is unavailable."""
    commit = _git(repo_root, "rev-parse", "HEAD")
    branch = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    dirty_output = _git(repo_root, "status", "--porcelain", "--untracked-files=no")
    return {
        "commit": commit,
        "branch": branch,
        "dirty": bool(dirty_output),
        "dirty_paths": [line for line in dirty_output.splitlines() if line.strip()],
    }


def source_manifest_hash(paths: Iterable[Path], repo_root: Path) -> str:
    lines = []
    for path in sorted(paths, key=str):
        try:
            relative = path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError as exc:
            raise GateError(f"source path outside the repository: {path}") from exc
        if not path.is_file():
            raise GateError(f"source manifest entry does not exist: {relative}")
        lines.append(f"{relative}:{sha256_file(path)}")
    return sha256_bytes("\n".join(lines).encode("utf-8"))


def capture_provenance(
    repo_root: Path,
    *,
    source_paths: Sequence[Path],
    protocol_sha256: str,
    manifest_hashes: dict[str, str],
    offsets_sha256: str,
) -> dict:
    return {
        "git": git_provenance(repo_root),
        "protocol_sha256": protocol_sha256,
        "offsets_sha256": offsets_sha256,
        "manifest_hashes": dict(manifest_hashes),
        "source_manifest_sha256": source_manifest_hash(source_paths, repo_root),
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit-learn": sklearn.__version__,
            "platform": sys.platform,
        },
        "captured_at": _utc_now(),
    }


def require_clean_tree(provenance: dict) -> None:
    """Accept either a captured provenance block or a bare git_provenance() result."""
    git = provenance.get("git", provenance)
    if git.get("dirty"):
        raise GateError(
            f"campaign requires a clean tracked tree; dirty paths: {git.get('dirty_paths', [])[:5]}"
        )


# --- fitted state -----------------------------------------------------------


def freeze_fitted_v21(
    out_dir: Path,
    *,
    fitted: dict,
    model,
    trials: pd.DataFrame,
    protocol: dict,
    protocol_hash: str,
    provenance: dict,
) -> dict:
    """Persist model + preprocessing + provenance; refuse once any marker exists."""
    assert_no_markers(out_dir)
    assert_fit_splits(trials, protocol)
    if "detector_thresholds" not in fitted:
        raise GateError(
            "fitted payload must carry the detector threshold table so the test evaluator "
            "never calibrates the comparator from test data"
        )
    detector_thresholds = detector_table(fitted["detector_thresholds"])
    out_dir.mkdir(parents=True, exist_ok=True)

    model_path = out_dir / _safe_model_filename(SAFE_MODEL_FILENAME)
    model_path.write_bytes(pickle.dumps(model))
    payload = {
        "phase": PROTOCOL_PHASE,
        "schema_version": FITTED_SCHEMA_VERSION,
        "protocol_version": protocol["version"],
        "protocol_sha256": protocol_hash,
        "model_id": fitted["model_id"],
        "features": fitted["features"],
        "dropped_features": fitted["dropped_features"],
        "imputation_medians": fitted["imputation_medians"],
        "thresholds": stratum_table(fitted["thresholds"]),
        "detector_thresholds": detector_thresholds,
        "counts": {
            "train_rows": fitted["train_rows"],
            "val_rows": fitted["val_rows"],
            "train_injected": fitted["train_injected"],
        },
        "model_file": model_path.name,
        "model_sha256": sha256_file(model_path),
        "provenance": provenance,
    }
    digest = write_json_with_sidecar(out_dir / "fitted.json", payload)
    return {"fitted.json": digest, "model.pkl": payload["model_sha256"]}


def load_fitted_v21(out_dir: Path, protocol_hash: str) -> dict:
    """Load frozen fitted state; every pointer and hash is re-verified."""
    path = out_dir / "fitted.json"
    if not path.is_file():
        raise GateError("no frozen fitted state: run the fit stage first")
    sidecar = out_dir / "fitted.sha256"
    if not sidecar.is_file():
        raise GateError("fitted.sha256 is missing; the fitted state is not frozen")
    payload = json.loads(path.read_text(encoding="utf-8"))
    digest = sha256_file(path)
    if sidecar.read_text(encoding="utf-8").split()[0] != digest:
        raise GateError("fitted.json does not match its recorded hash")
    if payload.get("schema_version") != FITTED_SCHEMA_VERSION:
        raise GateError("fitted state was not produced by protocol v2.3")
    if payload.get("protocol_sha256") != protocol_hash:
        raise GateError("fitted state was produced under a different protocol")
    model_name = _safe_model_filename(payload.get("model_file"))
    recorded_model_hash = payload.get("model_sha256")
    if not isinstance(recorded_model_hash, str):
        raise GateError("fitted state has no model_sha256")
    model_path = out_dir / model_name
    if not model_path.is_file() or sha256_file(model_path) != recorded_model_hash:
        raise GateError("model file does not match fitted.json")
    if "provenance" not in payload:
        raise GateError("fitted state has no provenance block")
    payload["_sha256"] = digest
    return payload


def campaign_preconditions(
    manifest_dir: Path,
    out_dir: Path,
    repo_root: Path,
    *,
    source_paths: Sequence[Path],
) -> dict:
    """Full fail-closed preflight. Reads no trial data and writes nothing."""
    protocol, protocol_hash = load_protocol_v21(manifest_dir / AUTHORIZED_PROTOCOL_NAME)
    manifests = validate_manifests(manifest_dir, protocol)
    _offsets, offsets_hash = load_frozen_offsets(manifest_dir, protocol)
    if out_dir.resolve() == manifest_dir.resolve():
        raise GateError("output directory must not be the manifest directory")
    assert_no_markers(out_dir)
    if (out_dir / "fitted.sha256").is_file():
        raise GateError("output directory already contains a frozen fitted artifact")
    provenance = capture_provenance(
        repo_root,
        source_paths=source_paths,
        protocol_sha256=protocol_hash,
        manifest_hashes=manifests,
        offsets_sha256=offsets_hash,
    )
    require_clean_tree(provenance)
    return {
        "protocol_hash": protocol_hash,
        "protocol_version": protocol["version"],
        "manifests": manifests,
        "offsets_sha256": offsets_hash,
        "provenance": provenance,
        "reads_test": False,
        "writes": [],
    }


# --- false-positive-rate reporting -----------------------------------------


def zero_fp_upper_bound(n: int, alpha: float = INTERVAL_ALPHA) -> float | None:
    """One-sided Clopper-Pearson upper bound when zero false positives are observed."""
    if n <= 0:
        return None
    return float(1.0 - alpha ** (1.0 / n))


def fpr_report(false_positives: int, null_trials: int, alpha: float = INTERVAL_ALPHA) -> dict:
    if null_trials <= 0:
        raise GateError("false-positive rate needs a positive denominator")
    if not 0 <= false_positives <= null_trials:
        raise GateError("false positives cannot exceed the denominator")
    report = {
        "false_positives": int(false_positives),
        "null_trials": int(null_trials),
        "fpr": false_positives / null_trials,
        "target_fpr": TARGET_FPR,
        "wilson": wilson_interval(false_positives, null_trials),
        "wilson_label": "trial-level and anti-conservative; never called cluster-adjusted",
    }
    if false_positives == 0:
        report["primary_interval"] = {
            "method": "clopper-pearson one-sided upper",
            "alpha": alpha,
            "upper": zero_fp_upper_bound(null_trials, alpha),
        }
    else:
        report["primary_interval"] = {
            "method": "trial-level; exact two-sided interval reported separately",
            "alpha": alpha,
        }
    return report


# --- paired comparison ------------------------------------------------------


def _paired_quarter_differences(frame: pd.DataFrame) -> tuple[dict[str, np.ndarray], float]:
    """Per-quarter paired differences, plus the pooled trial-weighted difference."""
    required = {"quarter", "trial_id", "rec_l7", "rec_physics"}
    missing = required - set(frame.columns)
    if missing:
        raise GateError(f"comparison frame is missing columns: {sorted(missing)}")
    if frame.empty:
        raise GateError("comparison frame is empty")
    if frame["trial_id"].duplicated().any():
        raise GateError("comparison frame has duplicate trial ids; pairing is undefined")

    differences = frame["rec_l7"].to_numpy(dtype=float) - frame["rec_physics"].to_numpy(dtype=float)
    per_quarter = {
        str(quarter): differences[np.asarray(index)]
        for quarter, index in frame.groupby("quarter").indices.items()
    }
    return per_quarter, float(np.mean(differences))


def _cluster_interval(
    per_quarter: dict[str, np.ndarray],
    clusters: list[str],
    pooled: float,
    resamples: int,
) -> dict:
    """Percentile interval as the primary result, BCa as a diagnostic on the same draws."""
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    picks = rng.integers(0, len(clusters), size=(resamples, len(clusters)))
    boot = np.empty(resamples, dtype=float)
    for index, pick in enumerate(picks):
        boot[index] = float(np.mean(np.concatenate([per_quarter[clusters[i]] for i in pick])))
    if not np.isfinite(boot).all():
        return {
            "low": None,
            "high": None,
            "bca": {"method": "bca", "available": False, "reason": "non-finite replicate"},
            "unreliable": True,
            "reasons": ["non-finite replicates"],
        }
    low, high = np.percentile(
        boot, [100 * INTERVAL_ALPHA / 2, 100 * (1 - INTERVAL_ALPHA / 2)], method="linear"
    )
    reasons = _unreliable_reasons(boot, per_quarter, clusters)
    return {
        "low": float(low),
        "high": float(high),
        "bca": _bca_interval(per_quarter, clusters, boot, pooled),
        "unreliable": bool(reasons),
        "reasons": reasons,
    }


def _unreliable_reasons(
    boot: np.ndarray, per_quarter: dict[str, np.ndarray], clusters: list[str]
) -> list[str]:
    reasons = []
    if np.unique(boot).size < 2:
        reasons.append("fewer than 2 distinct bootstrap values")
    contributing = sum(1 for q in clusters if float(np.mean(per_quarter[q])) != 0.0)
    if contributing < 3:
        reasons.append(f"only {contributing} of {len(clusters)} quarters contribute a difference")
    return reasons


def _bca_interval(
    per_quarter: dict[str, np.ndarray],
    clusters: list[str],
    boot: np.ndarray,
    pooled: float,
) -> dict:
    """Secondary/diagnostic BCa interval computed from the primary bootstrap draws."""
    count = len(clusters)
    jack = np.array(
        [
            np.mean(np.concatenate([per_quarter[clusters[j]] for j in range(count) if j != i]))
            for i in range(count)
        ]
    )
    jack_mean = float(jack.mean())
    denominator = float(np.sum((jack_mean - jack) ** 2))
    if denominator <= 0 or float(np.std(boot)) <= 0:
        return {"method": "bca", "available": False, "reason": "degenerate acceleration"}
    proportion = float(np.mean(boot < pooled))
    proportion = min(max(proportion, 1.0 / len(boot)), 1.0 - 1.0 / len(boot))
    z0 = float(norm.ppf(proportion))
    acceleration = float(np.sum((jack_mean - jack) ** 3) / (6 * denominator**1.5))
    try:
        adjusted = [
            float(norm.cdf(z0 + (z0 + z) / (1 - acceleration * (z0 + z))))
            for z in (norm.ppf(INTERVAL_ALPHA / 2), norm.ppf(1 - INTERVAL_ALPHA / 2))
        ]
    except FloatingPointError:  # pragma: no cover - defensive
        return {"method": "bca", "available": False, "reason": "undefined"}
    if not all(np.isfinite(adjusted)):
        return {"method": "bca", "available": False, "reason": "undefined"}
    low, high = np.percentile(boot, np.array(adjusted) * 100, method="linear")
    return {
        "method": "bca",
        "available": True,
        "low": float(low),
        "high": float(high),
        "diagnostic_only": True,
    }


def _gate_reasons(
    pooled: float,
    per_quarter: dict[str, np.ndarray],
    fpr: dict | None,
    degenerate_strata: Sequence[str],
) -> list[str]:
    """Every pre-registered reason that forces an inconclusive outcome."""
    reasons: list[str] = []
    if pooled == 0.0:
        reasons.append("pooled difference is exactly zero")
    else:
        sign = np.sign(pooled)
        opposite = [
            quarter
            for quarter, values in per_quarter.items()
            if np.sign(float(np.mean(values))) == -sign
        ]
        if len(opposite) >= 2:
            reasons.append(f"heterogeneity guard fired (opposite sign in {sorted(opposite)})")
    if fpr is not None and {"l7", "physics"} <= set(fpr):
        mismatch = abs(float(fpr["l7"]) - float(fpr["physics"]))
        if mismatch > MISMATCH_TOLERANCE:
            reasons.append(
                f"false-positive-rate mismatch {mismatch:.4f} exceeds {MISMATCH_TOLERANCE}"
            )
    if degenerate_strata:
        reasons.append(f"degenerate thresholds in strata {sorted(degenerate_strata)}")
    return reasons


def _final_status(pooled: float, low: float, mmd: float | None) -> tuple[str, list[str]]:
    if mmd is None:
        return "descriptive_only", [
            "minimum meaningful difference unset: practical superiority cannot be claimed"
        ]
    if low > 0.0 and pooled >= float(mmd):
        return "superior", []
    return "not_superior", []


def paired_comparison(
    frame: pd.DataFrame,
    *,
    mmd: float | None = MINIMUM_MEANINGFUL_DIFFERENCE,
    fpr: dict | None = None,
    degenerate_strata: Sequence[str] = (),
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> dict:
    """L7-minus-physics recall difference with cluster-aware uncertainty.

    Returns one of ``superior``, ``not_superior``, ``inconclusive`` or ``descriptive_only``.
    With the minimum meaningful difference unset the best possible outcome is
    ``descriptive_only``: a practical-superiority claim is structurally impossible here.

    ``mmd`` exists only to make decision D1 explicit and testable. Because the frozen
    protocol leaves the minimum meaningful difference unset, any non-None value is refused
    rather than silently applied; a caller cannot reclassify the result by supplying one.
    """
    if mmd is not None:
        raise GateError(
            "the frozen protocol leaves the minimum meaningful difference unset; "
            f"caller-supplied overrides are refused (got {mmd!r})"
        )
    if int(resamples) < 2:
        raise GateError(f"resamples must be at least 2, got {resamples!r}")
    per_quarter, pooled = _paired_quarter_differences(frame)
    clusters = sorted(per_quarter)
    quarter_means = {q: float(np.mean(v)) for q, v in per_quarter.items()}
    if len(clusters) < 3:
        return _comparison_result(
            "inconclusive",
            pooled,
            None,
            None,
            len(clusters),
            ["fewer than 3 clusters"],
            quarter_means=quarter_means,
        )

    interval = _cluster_interval(per_quarter, clusters, pooled, resamples)
    reasons = interval["reasons"] or _gate_reasons(pooled, per_quarter, fpr, degenerate_strata)
    if reasons:
        return _comparison_result(
            "inconclusive",
            pooled,
            interval["low"],
            interval["high"],
            len(clusters),
            reasons,
            bca=interval["bca"],
            quarter_means=quarter_means,
        )

    status, notes = _final_status(pooled, interval["low"], mmd)
    return _comparison_result(
        status,
        pooled,
        interval["low"],
        interval["high"],
        len(clusters),
        notes,
        bca=interval["bca"],
        quarter_means=quarter_means,
    )


def _comparison_result(
    status: str,
    estimate: float,
    low: float | None,
    high: float | None,
    clusters: int,
    reasons: list[str],
    *,
    bca: dict | None = None,
    quarter_means: dict | None = None,
) -> dict:
    return {
        "status": status,
        "estimate": estimate,
        "interval": {
            "method": "percentile",
            "primary": True,
            "low": low,
            "high": high,
            "alpha": INTERVAL_ALPHA,
        },
        "bca": bca or {"method": "bca", "available": False},
        "clusters": int(clusters),
        "reasons": reasons,
        "per_quarter": quarter_means or {},
        "practical_superiority_claim": False,
        "mmd": MINIMUM_MEANINGFUL_DIFFERENCE,
        "cluster_limitation": (
            "five clusters at most; the resample count is not a count of independent units"
        ),
    }


def combine_confirmatory(results: dict[str, dict]) -> dict:
    """Intersection-union across noise strata: every stratum must independently pass."""
    if not results:
        raise GateError("no stratum results to combine")
    statuses = {stratum: result["status"] for stratum, result in results.items()}
    unknown = {
        stratum: status
        for stratum, status in statuses.items()
        if status not in {"superior", "not_superior", "inconclusive", "descriptive_only"}
    }
    if unknown:
        raise GateError(f"unrecognised comparison status: {unknown}")
    if any(status == "inconclusive" for status in statuses.values()):
        overall = "inconclusive"
    elif any(status == "descriptive_only" for status in statuses.values()):
        overall = "descriptive_only"
    elif all(status == "superior" for status in statuses.values()):
        overall = "superior"
    else:
        overall = "not_superior"
    return {
        "status": overall,
        "per_stratum": statuses,
        "rule": "intersection-union; any stratum failing makes the overall result inconclusive",
        "practical_superiority_claim": False,
    }


__all__ = [
    "AUTHORIZED_PROTOCOL_NAME",
    "AUTHORIZED_PROTOCOL_SHA256",
    "MARKERS",
    "MARKER_ACCESS",
    "MARKER_GENERATION",
    "MINIMUM_MEANINGFUL_DIFFERENCE",
    "MIN_CALIBRATION_N",
    "TARGET_FPR",
    "assert_no_markers",
    "assert_strata_operative",
    "begin_marker",
    "calibrate_thresholds_v21",
    "campaign_preconditions",
    "capture_provenance",
    "choose_threshold_v21",
    "combine_confirmatory",
    "complete_marker",
    "effective_protocol",
    "exceedance",
    "fpr_report",
    "freeze_fitted_v21",
    "git_provenance",
    "load_experiment_config",
    "load_fitted_v21",
    "load_frozen_offsets",
    "load_protocol_v1",
    "load_protocol_v21",
    "marker_state",
    "paired_comparison",
    "require_clean_tree",
    "resolve_effective_protocol",
    "source_manifest_hash",
    "stratum_table",
    "validate_manifest_entry",
    "validate_manifests",
    "zero_fp_upper_bound",
]
