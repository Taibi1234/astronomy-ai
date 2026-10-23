"""Phase 11 Stage B1: synthetic-only fitting path on the authenticated B0 view.

The only approved mode is ``synthetic``. This module is a capability, not an authority: it
reads no quarter CSV, constructs no real rows, generates no test trial, touches no campaign
marker and evaluates nothing. Real campaign execution stays behind the unconditional refusal in
``phase11_runner.execute_real``, which this module does not import, edit or bypass.

Every entry point applies the same ordering:

1. the approved-mode gate runs first, before any data is inspected or any directory created;
2. the input boundary gate validates the frame (synthetic provenance tag, split and role
   vocabulary, label invariant, required nulls, feature columns) **before** fitting or feature
   use, and refuses real or test-split input;
3. output isolation is resolved before the first write;
4. only then are the frozen v2 helpers called: ``phase11.fit_models`` for the synthetic fit,
   ``phase11_v2.calibrate_thresholds_v21`` for the per-stratum thresholds and
   ``phase11_v2.freeze_fitted_v21`` for the eight-key payload plus provenance.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from . import phase11
from . import phase11_v2 as v2
from .phase11 import GateError
from .phase11_b2a import ROLE_INJECTION, ROLE_NULL, build_fit_split_frame
from .phase11_b2a import SOURCE as SYNTHETIC_SOURCE
from .phase11_runner import resolve_output_dir

MODE_SYNTHETIC = "synthetic"
APPROVED_MODES = (MODE_SYNTHETIC,)
FIT_SPLITS = ("train", "val")
ROLES = (ROLE_NULL, ROLE_INJECTION)
REQUIRED_COLUMNS = (
    "trial_id",
    "quarter",
    "split",
    "role",
    "requested_depth_ppm",
    "injected",
    "noise_condition",
    "source",
)
FITTED_PAYLOAD_KEYS = (
    "model_id",
    "features",
    "dropped_features",
    "imputation_medians",
    "thresholds",
    "detector_thresholds",
    "train_rows",
    "val_rows",
    "train_injected",
)
SCORE_COLUMN = "score"


# --- gates -------------------------------------------------------------------


def assert_approved_mode(mode: object) -> str:
    """Refuse any mode other than the approved synthetic one, before anything else."""
    if mode not in APPROVED_MODES:
        raise GateError(
            f"mode {mode!r} is not approved for B1; approved modes are {APPROVED_MODES}. "
            "Real campaign execution is not available through this module"
        )
    return str(mode)


def assert_approved_protocol(effective: object, protocol_hash: object) -> None:
    """Require the pinned v2.3 identity before any fitted state can be produced."""
    if not isinstance(effective, Mapping):
        raise GateError("effective protocol must be a mapping produced by B0")
    if effective.get("version") != v2.AUTHORIZED_PROTOCOL_VERSION:
        raise GateError(
            f"effective protocol version {effective.get('version')!r} is not the authorized "
            f"{v2.AUTHORIZED_PROTOCOL_VERSION!r}"
        )
    if protocol_hash != v2.AUTHORIZED_PROTOCOL_SHA256:
        raise GateError(f"protocol hash {protocol_hash!r} is not the authorized v2.3 pin")


def assert_approved_provenance(provenance: object, effective: object) -> str:
    """The captured provenance supplies the protocol hash; it must be the active pin."""
    if not isinstance(provenance, Mapping):
        raise GateError("provenance must be the captured dict from capture_provenance")
    digest = provenance.get("protocol_sha256")
    if not isinstance(digest, str):
        raise GateError(
            "provenance has no protocol_sha256; capture it with phase11_v2.capture_provenance"
        )
    assert_approved_protocol(effective, digest)
    return digest


def _resolve_feature_columns(effective: Mapping, model_id: str | None) -> tuple[str, list[str]]:
    if model_id is None:
        features_block = effective.get("features")
        if not isinstance(features_block, Mapping):
            raise GateError("effective protocol has no features block")
        model_id = features_block.get("primary_model")
    if not isinstance(model_id, str) or not model_id:
        raise GateError("no model id: pass model_id or use a view that names primary_model")
    return model_id, phase11.feature_columns(dict(effective), model_id)


def assert_synthetic_frame(
    frame: object,
    effective: Mapping,
    *,
    model_id: str | None = None,
) -> tuple[str, list[str]]:
    """Input boundary gate. Runs before any feature extraction or fitting.

    Refuses real-source rows, test-split rows, foreign roles, label drift, duplicate trial
    identities, missing feature columns and a validation split without nulls.
    """
    if not isinstance(frame, pd.DataFrame):
        raise GateError("B1 accepts a pandas DataFrame of synthetic rows only")
    if frame.empty:
        raise GateError("B1 frame is empty")
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise GateError(f"B1 frame is missing required columns {missing}")

    _assert_synthetic_source(frame)
    _assert_fit_vocabulary(frame)
    _assert_labels_and_nulls(frame)
    if bool(frame["trial_id"].duplicated().any()):
        raise GateError("duplicate trial_id values; row identity must be unique")

    resolved_model, columns = _resolve_feature_columns(effective, model_id)
    absent = [column for column in columns if column not in frame.columns]
    if absent:
        raise GateError(f"frame is missing the model feature columns {absent}")

    phase11.assert_fit_splits(frame, effective)
    return resolved_model, columns


def _assert_synthetic_source(frame: pd.DataFrame) -> None:
    sources = sorted({str(value) for value in frame["source"].unique()})
    if sources != [SYNTHETIC_SOURCE]:
        raise GateError(
            f"B1 accepts synthetic fixtures only; frame sources {sources} are not "
            f"{SYNTHETIC_SOURCE!r}. Real campaign rows are refused before feature extraction"
        )


def _assert_fit_vocabulary(frame: pd.DataFrame) -> None:
    splits = {str(value) for value in frame["split"].unique()}
    if "test" in splits:
        raise GateError("B1 must never see test-split rows; refusing before any extraction")
    unexpected = sorted(splits - set(FIT_SPLITS))
    if unexpected:
        raise GateError(f"unexpected splits {unexpected}; B1 accepts only {list(FIT_SPLITS)}")
    roles = {str(value) for value in frame["role"].unique()}
    unexpected_roles = sorted(roles - set(ROLES))
    if unexpected_roles:
        raise GateError(f"unexpected roles {unexpected_roles}; B1 accepts only {list(ROLES)}")


def _assert_labels_and_nulls(frame: pd.DataFrame) -> None:
    expected = frame["requested_depth_ppm"] > 0
    if not bool((frame["injected"].astype(bool) == expected).all()):
        raise GateError("label invariant violated: injected != (requested_depth_ppm > 0)")
    nulls = frame[frame["role"] == ROLE_NULL]
    if bool(nulls["injected"].astype(bool).any()):
        raise GateError("null windows must carry injected=False")
    if nulls[nulls["split"] == "val"].empty:
        raise GateError(
            "validation nulls are required to calibrate the threshold; the frame has none"
        )


def assert_approved_split_map(split_map: object) -> dict[str, str]:
    """Refuse a test or unknown split before B2a constructs any row."""
    if not isinstance(split_map, Mapping) or not split_map:
        raise GateError("split_map must be a non-empty mapping of quarter -> split")
    approved: dict[str, str] = {}
    for quarter, split in split_map.items():
        if not isinstance(quarter, str) or not quarter:
            raise GateError("split_map keys must be non-empty quarter identifiers")
        if not isinstance(split, str):
            raise GateError(f"split for {quarter} is not a string: {split!r}")
        if split == "test":
            raise GateError(
                "B1 builds fit splits only; test-split input is refused before row construction"
            )
        if split not in FIT_SPLITS:
            raise GateError(f"unsupported split {split!r}; allowed splits are {list(FIT_SPLITS)}")
        approved[quarter] = split
    return approved


# --- gated synthetic path ----------------------------------------------------


def build_frame_for_fit(
    *,
    effective: Mapping,
    split_map: Mapping[str, str],
    seed: int,
    mode: object = MODE_SYNTHETIC,
    **builder_kwargs,
) -> pd.DataFrame:
    """Mode gate, then split gate, then B2a row construction. Nothing is built on refusal."""
    assert_approved_mode(mode)
    approved = assert_approved_split_map(split_map)
    return build_fit_split_frame(
        effective=effective, split_map=approved, seed=seed, **builder_kwargs
    )


def _calibration_scores(frame: pd.DataFrame, fitted: dict) -> pd.DataFrame:
    """Score validation nulls with the fitted preprocessing, then hand them to v2 calibration."""
    val_nulls = frame[(frame["split"] == "val") & (frame["role"] == ROLE_NULL)].copy()
    if val_nulls.empty:
        raise GateError("validation nulls are required to calibrate the threshold")
    kept = list(fitted["features"])
    medians = np.asarray(fitted["imputation_medians"], dtype=float)
    matrix = val_nulls[kept].to_numpy(dtype=float)
    filled = np.where(np.isfinite(matrix), matrix, medians)
    val_nulls[SCORE_COLUMN] = np.asarray(fitted["model"].predict_proba(filled)[:, 1], dtype=float)
    return val_nulls


def fit_synthetic(
    *,
    effective: Mapping,
    frame: pd.DataFrame,
    out_dir: Path,
    provenance: dict,
    manifest_dir: Path,
    repo_root: Path,
    mode: object = MODE_SYNTHETIC,
    model_id: str | None = None,
) -> dict:
    """Fit, calibrate and freeze on synthetic rows only; return the produced artifact hashes."""
    assert_approved_mode(mode)
    protocol_hash = assert_approved_provenance(provenance, effective)
    resolved_model, _columns = assert_synthetic_frame(frame, effective, model_id=model_id)
    out = resolve_output_dir(Path(out_dir), manifest_dir=manifest_dir, repo_root=repo_root)
    v2.require_clean_tree(provenance)

    fitted = phase11.fit_models(frame, dict(effective), resolved_model)
    calibration = _calibration_scores(frame, fitted)
    thresholds = v2.calibrate_thresholds_v21(
        calibration,
        dict(effective),
        score_column=SCORE_COLUMN,
        splits=FIT_SPLITS[1:],
        role=ROLE_NULL,
        floor=effective["thresholds"]["fitted_models"]["floor_snr"],
        score_supremum=1.0,
        context=f"B1|{resolved_model}",
    )
    # The physics comparator's operating point is calibrated on the same train+val nulls and
    # frozen beside the L7 table, so the test evaluator never calibrates from test data.
    detector_thresholds = phase11.calibrate_detector_thresholds(frame, dict(effective))

    payload = {
        "model_id": resolved_model,
        "features": list(fitted["features"]),
        "dropped_features": list(fitted["dropped_features"]),
        "imputation_medians": list(fitted["imputation_medians"]),
        "thresholds": thresholds,
        "detector_thresholds": detector_thresholds,
        "train_rows": int(fitted["train_rows"]),
        "val_rows": int(fitted["val_rows"]),
        "train_injected": int(fitted["train_injected"]),
    }
    missing = [key for key in FITTED_PAYLOAD_KEYS if key not in payload]
    if missing:  # pragma: no cover - defensive: the literal above is the contract
        raise GateError(f"fitted payload is missing {missing}")

    artifacts = v2.freeze_fitted_v21(
        out,
        fitted=payload,
        model=fitted["model"],
        trials=frame,
        protocol=dict(effective),
        protocol_hash=protocol_hash,
        provenance=provenance,
    )
    return {
        "mode": MODE_SYNTHETIC,
        "model_id": resolved_model,
        "out_dir": str(out),
        "artifacts": artifacts,
        "thresholds": v2.stratum_table(thresholds),
        "payload_keys": list(payload),
        "fitted_json_sha256": artifacts.get("fitted.json"),
    }
