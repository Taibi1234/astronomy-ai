"""Phase 11b stages 0-1: frozen protocol, materialized offsets, and the gated runner.

Nothing in this module is executed by the Phase 11b implementation review: it defines
the protocol, writes the deterministic offset draws, and implements the campaign and
evaluation code behind gates that refuse test access until the protocol and the fitted
state are frozen and hashed.

Enforcement summary
-------------------
* ``fit_models`` refuses any frame that contains a row outside ``train``/``val``.
* ``feature_columns`` refuses forbidden (ground-truth) columns.
* ``choose_threshold`` records its scope and refuses test rows in its input.
* ``freeze_fitted`` writes ``fitted.json`` + ``model.pkl`` + ``fitted.sha256`` and refuses
  to run after a test evaluation has been recorded.
* ``evaluate_test`` requires a hash-matched protocol and fitted state, allows exactly one
  read of the test rows, and writes an auditable ``test_access.json`` ledger.
* ``run_campaign(split_group="test")`` requires a frozen fitted artifact first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import re
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn
import transit_injection as ti
from scipy.stats import norm
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    matthews_corrcoef,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from . import core
from . import generalization as gen

PROTOCOL_VERSION = "phase11b-protocol-v1"
OFFSETS_VERSION = "phase11b-offsets-v1"
TARGET_FPR = 0.05
MODEL_SEED = 20261025
BOOTSTRAP_SEED = 20261024
BOOTSTRAP_RESAMPLES = 10_000
OFFSET_HALF_DAYS = gen.OFFSET_HALF_DAYS
TIMING_TOLERANCE_DAYS = core.TOLERANCE_DAYS

SAFE_MODEL_FILENAME = "model.pkl"
QUARTER_PATTERN = re.compile(r"^Q\d{2}$")
EXPECTED_PHASE = "11b"
EXPECTED_SCHEMA_VERSION = 1


def _safe_model_filename(name: object) -> str:
    """Fitted state may only reference the single safe model filename."""
    if not isinstance(name, str) or name != SAFE_MODEL_FILENAME:
        raise GateError(
            f"fitted state must reference {SAFE_MODEL_FILENAME!r}, got {name!r}"
        )
    path = Path(name)
    if path.is_absolute() or path.name != name or ".." in path.parts:
        raise GateError(f"unsafe model filename: {name!r}")
    return name


def validate_quarter(quarter: object) -> str:
    """Quarter identifiers are used in filenames; only Q<two digits> is allowed."""
    if not isinstance(quarter, str) or QUARTER_PATTERN.fullmatch(quarter) is None:
        raise GateError(f"invalid quarter identifier: {quarter!r}")
    return quarter


def require_noise_strata(
    present, expected, *, context: str, allow_extra: bool = False
) -> None:
    """Refuse calibration/reporting when a declared noise stratum is absent."""
    present_set = {str(value) for value in present}
    expected_set = {str(value) for value in expected}
    missing = sorted(expected_set - present_set)
    extra = sorted(present_set - expected_set)
    if missing:
        raise GateError(f"{context}: missing noise strata {missing}")
    if extra and not allow_extra:
        raise GateError(f"{context}: unexpected noise strata {extra}")

# Detector operating-point reporting. Protocol v1 fixes the threshold rule but does
# not yet record these reporting fields; see reports/phase11b_implementation.md §6.
DETECTOR_REPORT_SPEC = {
    "score": "snr",
    "detected": "snr > threshold[noise_condition]",
    "recovered": (
        "injected and detected and |delta_est_days - delta_true_days| <= "
        "timing_tolerance_days"
    ),
    "timing_tolerance_days": TIMING_TOLERANCE_DAYS,
    "strata": ["noise_condition"],
    "pooled": "all test windows",
    "fpr": "false positives / null trials, per stratum and pooled, Wilson + quarter bootstrap",
    "recall": "recovered / injected trials, per depth and pooled, Wilson + quarter bootstrap",
    "clusters": "quarter",
    "comparison_rule": (
        "physics and ML are compared on the same test trial ids at the same FPR target; "
        "differences are paired by quarter and reported with cluster intervals"
    ),
}


class GateError(RuntimeError):
    """Raised when a leakage or freeze-order gate is violated."""


# --- stage 0: protocol -------------------------------------------------------


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def manifest_hashes(manifest_dir: Path) -> dict[str, str]:
    names = (
        "split.json",
        "windows_primary.json",
        "windows_sensitivity.json",
        "null_library.json",
        "experiment_config.json",
    )
    missing = [name for name in names if not (manifest_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing manifests: {missing}")
    return {name: sha256_file(manifest_dir / name) for name in names}


def build_protocol(manifest_dir: Path) -> dict[str, Any]:
    """Protocol contents. Every value here is frozen before any campaign runs."""
    ladder = {
        entry["id"]: {
            "kind": entry["kind"],
            "features": list(entry["features"]),
            "note": entry["note"],
        }
        for entry in gen.ML_LADDER
    }
    return {
        "phase": "11b",
        "schema_version": 1,
        "status": "frozen before campaign; no campaign executed at freeze time",
        "version": PROTOCOL_VERSION,
        "target": "Kepler-10 b",
        "unit_of_independence": "kepler quarter",
        "manifests": manifest_hashes(manifest_dir),
        "seeds": {
            "split": gen.SPLIT_SEED,
            "offsets": gen.OFFSET_SEED,
            "model": MODEL_SEED,
            "bootstrap": BOOTSTRAP_SEED,
        },
        "features": {
            "detector_outputs": list(gen.DETECTOR_OUTPUTS),
            "flux_features": list(gen.FLUX_FEATURES_FULL),
            "definitions": {
                "snr": "matched-filter dip significance from core.detect, computed from flux only",
                "depth_est_ppm": "matched-filter amplitude converted to ppm",
                "sigma_ppm": "robust out-of-transit scatter (1.4826 * MAD)",
                "min_depth_ppm": "median(flux) - min(flux), in ppm (depth proxy)",
                "std_ppm": "standard deviation of flux, in ppm",
                "mad_ppm": "median absolute deviation of flux about its median",
                "gap_fraction": "fraction of cadence gaps > 0.05 d inside the window",
                "mean_flux": "mean normalized flux of the window",
                "n_points": "cadence count of the window",
            },
            "sets": ladder,
            "primary_model": "L7_detector_plus_clean_flux",
            "ablation_diagnostic": "L4_flux_full vs L5_flux_without_depth_proxy",
            "forbidden": list(gen.FORBIDDEN_FEATURE_COLUMNS),
        },
        "preprocessing": {
            "imputation": "median fitted on train rows only; non-finite median -> 0.0",
            "constant_feature_drop": "features with zero train variance are dropped and recorded",
            "scaling": "StandardScaler fitted inside the pipeline on train rows only",
            "feature_selection": "none; feature sets are frozen in this protocol",
            "hyperparameter_search": "none",
            "fit_splits": ["train"],
        },
        "models": {
            "logistic_regression": {
                "class": "sklearn.linear_model.LogisticRegression",
                "params": {
                    "C": 1.0,
                    "max_iter": 1000,
                    "solver": "lbfgs",
                    "class_weight": None,
                    "random_state": MODEL_SEED,
                },
            },
            "random_forest": {
                "class": "sklearn.ensemble.RandomForestClassifier",
                "params": {
                    "n_estimators": 200,
                    "max_depth": 6,
                    "n_jobs": 1,
                    "class_weight": None,
                    "random_state": MODEL_SEED,
                },
            },
            "dummy": {
                "class": "sklearn.dummy.DummyClassifier",
                "params": {"strategy": "stratified", "random_state": MODEL_SEED},
            },
            "selection": "none; L7 is pre-registered as primary",
        },
        "thresholds": {
            "target_fpr": TARGET_FPR,
            "detector": {
                "pool": "train+val null windows, per noise condition",
                "rule": "max(3.0, p95 of calibration null S/N)",
                "floor_snr": 3.0,
            },
            "fitted_models": {
                "pool": "validation null windows only",
                "rule": "p95 of validation null scores",
                "floor_snr": None,
            },
            "percentile_method": "linear",
            "comparison": "strict '>' (score > threshold means detected)",
            "tie_rule": (
                "raise the threshold to the next observed score until the calibration "
                "exceedance rate is <= target; never lower it below the empirical p95"
            ),
        },
        "metrics": {
            "primary": ["roc_auc", "recall_at_calibrated_fpr"],
            "secondary": [
                "pr_auc_with_prevalence",
                "mcc",
                "balanced_accuracy",
                "brier",
                "precision",
                "recall",
            ],
            "f1": "reported with prevalence and no-skill F1; never used for selection",
            "no_skill_f1": "2p/(1+p) with p the evaluation prevalence",
        },
        "bootstrap": {
            "method": "BCa",
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "cluster": "quarter",
            "percentile_method": "linear",
            "fallback": "percentile bootstrap if BCa acceleration is undefined",
            "report": "interval, cluster count k, and resample count",
        },
        "test_access": {
            "reads": 1,
            "requires": ["protocol.json hash match", "fitted.sha256 match", "manifests hash match"],
            "ledger": "test_access.json",
            "rule": (
                "test rows may be read only after fitted.sha256 exists; the second read raises; "
                "campaign generation for test windows also requires the frozen fitted artifact"
            ),
        },
        "campaign": {
            "modes": {
                "smoke": {
                    "quarters": ["Q00", "Q01", "Q04"],
                    "window_days": 5.0,
                    "split_group": "fit",
                    "note": "train+val only; exercises the pipeline without reading test",
                },
                "full": {"window_days": 5.0, "split_groups": ["fit", "test"]},
                "sensitivity": {"window_days": 3.0, "split_groups": ["fit", "test"]},
            },
            "order": [
                "campaign fit (train+val)",
                "fit models and detector thresholds",
                "freeze fitted.json + model.pkl + fitted.sha256",
                "campaign test (test quarters only)",
                "evaluate test once",
            ],
        },
        "environment": {
            "python": f"{__import__('sys').version.split()[0]}",
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit-learn": sklearn.__version__,
        },
    }


# --- stage 0: offsets --------------------------------------------------------


def derive_seed(base_seed: int, label: str) -> int:
    """Deterministic sub-seed so the two window lengths never share draws."""
    digest = hashlib.sha256(f"{base_seed}|{label}".encode()).hexdigest()
    return int(digest[:8], 16)


def build_offsets(windows: list[dict], window_days: float, seed: int = gen.OFFSET_SEED) -> dict:
    """Hidden phase offsets, keyed only by quarter, window index and window length.

    Roles, splits, flux and any outcome are deliberately absent from the key.
    """
    ordered = sorted(windows, key=lambda w: (w["quarter"], w["window_index"]))
    rng = np.random.default_rng(derive_seed(seed, f"window_days={window_days:.2f}"))
    draws = []
    for window in ordered:
        values = np.round(
            rng.uniform(-OFFSET_HALF_DAYS, OFFSET_HALF_DAYS, size=gen.OFFSET_DRAWS), 6
        )
        draws.append(
            {
                "quarter": window["quarter"],
                "window_index": int(window["window_index"]),
                "offsets_days": [float(v) for v in values],
            }
        )
    flat = [value for draw in draws for value in draw["offsets_days"]]
    return {
        "phase": "11b",
        "schema_version": 1,
        "version": OFFSETS_VERSION,
        "window_days": window_days,
        "seed": seed,
        "derived_seed": derive_seed(seed, f"window_days={window_days:.2f}"),
        "rule": (
            "per-length derived seed -> numpy default_rng -> uniform(-0.10, 0.10), "
            "two draws per window in canonical (quarter, window_index) order, rounded to 1e-6 d"
        ),
        "half_days": OFFSET_HALF_DAYS,
        "draws_per_window": gen.OFFSET_DRAWS,
        "counts": {"windows": len(draws), "values": len(flat)},
        "bounds": {"min": round(min(flat), 6), "max": round(max(flat), 6)},
        "draws": draws,
    }


def build_stage0(manifest_dir: Path) -> dict[str, dict]:
    protocol = build_protocol(manifest_dir)
    primary = json.loads((manifest_dir / "windows_primary.json").read_text(encoding="utf-8"))
    sensitivity = json.loads(
        (manifest_dir / "windows_sensitivity.json").read_text(encoding="utf-8")
    )
    offsets = {
        "phase": "11b",
        "schema_version": 1,
        "version": OFFSETS_VERSION,
        "seed": gen.OFFSET_SEED,
        "manifests": protocol["manifests"],
        "by_window_length": {
            "5.0": build_offsets(primary["windows"], 5.0),
            "3.0": build_offsets(sensitivity["windows"], 3.0),
        },
    }
    return {"protocol.json": protocol, "offsets.json": offsets}


def write_json_with_sidecar(path: Path, payload: dict) -> str:
    """Write JSON as UTF-8 bytes and record the raw-file SHA-256.

    ``Path.write_text`` would translate ``\\n`` to CRLF on Windows, so the hash and
    the file bytes would disagree with ``sha256sum``. Writing bytes keeps them equal.
    """
    data = (json.dumps(payload, indent=2, sort_keys=False) + "\n").encode("utf-8")
    path.write_bytes(data)
    digest = sha256_bytes(data)
    path.with_name(path.name.replace(".json", ".sha256")).write_bytes(
        f"{digest}  {path.name}\n".encode()
    )
    return digest


def write_stage0(out_dir: Path, manifest_dir: Path) -> dict[str, str]:
    """Write protocol/offsets plus sha256 sidecars; return the hashes."""
    artifacts = build_stage0(manifest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        name: write_json_with_sidecar(out_dir / name, payload)
        for name, payload in artifacts.items()
    }


def load_frozen_json(
    path: Path,
    *,
    expected_phase: str | None = None,
    expected_schema: int | None = None,
) -> tuple[dict, str]:
    """Read a JSON artifact, verify its bytes and optionally its schema header."""
    raw = path.read_bytes()
    digest = sha256_bytes(raw)
    sidecar = path.with_name(path.name.replace(".json", ".sha256"))
    if not sidecar.is_file():
        raise GateError(f"missing hash sidecar for {path.name}")
    recorded = sidecar.read_text(encoding="utf-8").split()[0]
    if recorded != digest:
        raise GateError(f"{path.name} does not match its recorded hash")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"{path.name} is not readable JSON") from exc
    if expected_phase is not None and payload.get("phase") != expected_phase:
        raise GateError(
            f"{path.name} phase {payload.get('phase')!r} != expected {expected_phase!r}"
        )
    if expected_schema is not None and payload.get("schema_version") != expected_schema:
        raise GateError(
            f"{path.name} schema_version {payload.get('schema_version')!r} "
            f"!= expected {expected_schema!r}"
        )
    return payload, digest


def assert_protocol_manifests(protocol: dict, manifest_dir: Path) -> None:
    if protocol.get("manifests") != manifest_hashes(manifest_dir):
        raise GateError("protocol was frozen against different manifests")


# --- stage 1: trial plan -----------------------------------------------------


def plan_trials(windows: list[dict], protocol: dict, split_group: str) -> pd.DataFrame:
    """Deterministic trial list; no flux, no detector, no outcomes.

    ``split_group='fit'`` yields train+val rows only; ``'test'`` yields test rows only.
    """
    allowed = {"fit": {"train", "val"}, "test": {"test"}}
    if split_group not in allowed:
        raise ValueError(f"split_group must be one of {sorted(allowed)}")
    splits = allowed[split_group]
    rows = []
    for window in windows:
        if window["split"] not in splits:
            continue
        # "null" is a pandas default NA token, so the trial-level vocabulary uses
        # "null_window"; the manifest keeps "null" because it is frozen.
        role = "null_window" if window["role"] == "null" else "injection"
        conditions = [(0.0, False)] if role == "null_window" else [
            (depth, True) for depth in gen.INJECTION_DEPTHS_PPM
        ] + [(gen.CONTROL_DEPTH_PPM, False)]
        for depth, injected in conditions:
            for offset_index in range(gen.OFFSET_DRAWS):
                for noise in gen.NOISE_CONDITIONS:
                    rows.append(
                        {
                            "trial_id": (
                                f"{window['quarter']}-{window['window_index']}-"
                                f"d{int(depth)}-o{offset_index}-{noise}"
                            ),
                            "quarter": window["quarter"],
                            "window_index": int(window["window_index"]),
                            "window_id": f"{window['quarter']}:{window['window_index']}",
                            "split": window["split"],
                            "role": role,
                            "requested_depth_ppm": float(depth),
                            "injected": bool(injected),
                            "offset_index": int(offset_index),
                            "noise_condition": noise,
                        }
                    )
    return pd.DataFrame(rows)


# --- stage 1: gates ----------------------------------------------------------


def feature_columns(protocol: dict, model_id: str) -> list[str]:
    sets = protocol["features"]["sets"]
    if model_id not in sets:
        raise GateError(f"unknown model id: {model_id}")
    features = list(sets[model_id]["features"])
    forbidden = set(protocol["features"]["forbidden"]) & set(features)
    if forbidden:
        raise GateError(f"{model_id} uses forbidden columns: {sorted(forbidden)}")
    allowed = set(protocol["features"]["detector_outputs"]) | set(
        protocol["features"]["flux_features"]
    )
    unknown = set(features) - allowed
    if unknown:
        raise GateError(f"{model_id} uses undeclared features: {sorted(unknown)}")
    return features


def assert_fit_splits(frame: pd.DataFrame, protocol: dict) -> None:
    """Refuse any row that is not a declared fitting split."""
    if "split" not in frame.columns:
        raise GateError("fitting frame has no split column")
    fit_splits = set(protocol["preprocessing"]["fit_splits"]) | {"val"}
    extra = set(frame["split"].unique()) - fit_splits
    if extra:
        raise GateError(f"fitting frame contains non-fitting splits: {sorted(extra)}")


def choose_threshold(
    scores: np.ndarray,
    *,
    target_fpr: float,
    scope: str,
    floor: float | None = None,
    comparison: str = ">",
) -> dict:
    """Empirical (1 - target) quantile with an explicit tie rule and provenance."""
    values = np.asarray(scores, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError("no finite scores to calibrate on")
    if comparison != ">":
        raise ValueError("only the pre-registered strict '>' comparison is supported")

    quantile = float(np.percentile(values, 100 * (1 - target_fpr), method="linear"))
    threshold = max(floor, quantile) if floor is not None else quantile
    candidates = np.unique(values[values >= threshold])
    for candidate in candidates:
        if float(np.mean(values > candidate)) <= target_fpr:
            threshold = float(candidate)
            break
    exceedance = float(np.mean(values > threshold))
    if exceedance > target_fpr:
        raise GateError("tie rule could not bring calibration exceedance under target")

    return {
        "threshold": float(threshold),
        "quantile_p95": quantile,
        "floor": floor,
        "floor_applied": bool(floor is not None and floor >= quantile),
        "scope": scope,
        "n": int(values.size),
        "calibration_exceedance": exceedance,
        "target_fpr": target_fpr,
        "comparison": comparison,
        "percentile_method": "linear",
        "tie_rule": "smallest observed score at or above the quantile with exceedance <= target",
    }


def calibrate_detector_thresholds(
    trials: pd.DataFrame, protocol: dict
) -> dict[str, dict]:
    """Detector thresholds from train+val nulls, per noise condition."""
    frame = trials[trials["role"] == "null_window"]
    if (frame["split"] == "test").any():
        raise GateError("detector calibration frame contains test rows")
    allowed = {"train", "val"}
    extra = set(frame["split"].unique()) - allowed
    if extra:
        raise GateError(f"unexpected calibration splits: {sorted(extra)}")
    require_noise_strata(
        frame["noise_condition"].unique(),
        protocol["injection"]["noise_conditions"],
        context="detector calibration",
    )
    thresholds = {}
    for noise, group in frame.groupby("noise_condition"):
        thresholds[str(noise)] = choose_threshold(
            group["snr"].to_numpy(),
            target_fpr=protocol["thresholds"]["target_fpr"],
            scope=f"detector|{noise}|train+val nulls",
            floor=protocol["thresholds"]["detector"]["floor_snr"],
        )
    return thresholds


def fit_models(
    trials: pd.DataFrame,
    protocol: dict,
    model_id: str,
    model_factory=None,
) -> dict:
    """Fit preprocessing and one model on train rows; calibrate on validation nulls."""
    assert_fit_splits(trials, protocol)
    features = feature_columns(protocol, model_id)
    train = trials[trials["split"] == "train"]
    val = trials[trials["split"] == "val"]
    if train.empty or val.empty:
        raise GateError("both train and validation rows are required")

    matrix = train[features].to_numpy(dtype=float)
    medians = np.nanmedian(matrix, axis=0)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    filled = np.where(np.isfinite(matrix), matrix, medians)
    variances = np.var(filled, axis=0)
    keep = variances > 0
    dropped = [feature for feature, kept in zip(features, keep, strict=True) if not kept]
    kept_features = [feature for feature, kept in zip(features, keep, strict=True) if kept]
    if not kept_features:
        raise GateError("all features are constant on train")

    factory = model_factory or _default_factory(model_id, protocol)
    model = factory()
    x_train = np.where(
        np.isfinite(train[kept_features].to_numpy(dtype=float)),
        train[kept_features].to_numpy(dtype=float),
        medians[keep],
    )
    model.fit(x_train, train["injected"].to_numpy(dtype=int))

    val_nulls = val[val["role"] == "null_window"]
    if val_nulls.empty:
        raise GateError("validation nulls are required to calibrate the threshold")
    x_val = np.where(
        np.isfinite(val_nulls[kept_features].to_numpy(dtype=float)),
        val_nulls[kept_features].to_numpy(dtype=float),
        medians[keep],
    )
    scores = model.predict_proba(x_val)[:, 1]
    threshold = choose_threshold(
        scores,
        target_fpr=protocol["thresholds"]["target_fpr"],
        scope=f"{model_id}|validation nulls",
        floor=protocol["thresholds"]["fitted_models"]["floor_snr"],
    )
    return {
        "model_id": model_id,
        "features": kept_features,
        "dropped_features": dropped,
        "imputation_medians": [float(v) for v in medians[keep]],
        "threshold": threshold,
        "train_rows": int(len(train)),
        "val_rows": int(len(val)),
        "train_injected": int(train["injected"].sum()),
        # in-memory only; freeze_fitted persists model.pkl and records its hash
        "model": model,
    }


def _default_factory(model_id: str, protocol: dict):
    """Dummy for L1; logistic regression for every other fitted ladder entry."""
    params = protocol["models"]
    if model_id == "L0_no_skill_all_positive":
        raise GateError("L0 is analytic and is never fitted")
    if model_id == "L1_dummy_stratified":
        return lambda: DummyClassifier(**params["dummy"]["params"])
    known = set(protocol["features"]["sets"]) - {"L0_no_skill_all_positive", "L1_dummy_stratified"}
    if model_id not in known:
        raise GateError(f"no default model for {model_id}")
    return lambda: Pipeline(
        [
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(**params["logistic_regression"]["params"])),
        ]
    )


# --- stage 1: freeze and evaluate -------------------------------------------


def _train_fingerprint(trials: pd.DataFrame, features: list[str]) -> str:
    payload = trials[["trial_id", "split", *features]].to_csv(index=False).encode("utf-8")
    return sha256_bytes(payload)


def freeze_fitted(
    out_dir: Path,
    *,
    fitted: dict,
    model,
    trials: pd.DataFrame,
    protocol: dict,
    protocol_hash: str,
) -> dict:
    """Persist preprocessing/model state + provenance, then hash it."""
    if (out_dir / "test_access.json").is_file():
        raise GateError("refusing to freeze after a test evaluation was recorded")
    out_dir.mkdir(parents=True, exist_ok=True)
    assert_fit_splits(trials, protocol)

    model_path = out_dir / SAFE_MODEL_FILENAME
    model_path.write_bytes(pickle.dumps(model))
    train = trials[trials["split"] == "train"]
    payload = {
        "phase": "11b",
        "schema_version": 1,
        "model_id": fitted["model_id"],
        "protocol_sha256": protocol_hash,
        "features": fitted["features"],
        "dropped_features": fitted["dropped_features"],
        "imputation_medians": fitted["imputation_medians"],
        "threshold": fitted["threshold"],
        "counts": {
            "train_rows": fitted["train_rows"],
            "val_rows": fitted["val_rows"],
            "train_injected": fitted["train_injected"],
        },
        "train_fingerprint": _train_fingerprint(train, fitted["features"]),
        "model_file": model_path.name,
        "model_sha256": sha256_file(model_path),
        "environment": {
            "python": __import__("sys").version.split()[0],
            "scikit-learn": sklearn.__version__,
            "numpy": np.__version__,
        },
    }
    digest = write_json_with_sidecar(out_dir / "fitted.json", payload)
    return {"fitted.json": digest, "model.pkl": payload["model_sha256"]}


def load_fitted(out_dir: Path, protocol_hash: str) -> dict:
    if not (out_dir / "fitted.json").is_file():
        raise GateError("no frozen fitted state: run the fit stage first")
    fitted, digest = load_frozen_json(out_dir / "fitted.json")
    if fitted.get("protocol_sha256") != protocol_hash:
        raise GateError("fitted state was produced under a different protocol")
    model_name = _safe_model_filename(fitted.get("model_file"))
    model_path = out_dir / model_name
    if not model_path.is_file() or sha256_file(model_path) != fitted["model_sha256"]:
        raise GateError("model file does not match fitted.json")
    fitted["_sha256"] = digest
    return fitted


def assert_test_generation_allowed(out_dir: Path) -> None:
    if not (out_dir / "fitted.sha256").is_file():
        raise GateError("test trials may not be generated before fitted.sha256 exists")


def detection_metrics(y_true, scores, threshold: float) -> dict:
    y_true = np.asarray(y_true, dtype=int)
    scores = np.asarray(scores, dtype=float)
    pred = (scores > threshold).astype(int)
    prevalence = float(np.mean(y_true == 1)) if y_true.size else 0.0
    out = {
        "n": int(y_true.size),
        "positive": int(y_true.sum()),
        "negative": int((y_true == 0).sum()),
        "prevalence": prevalence,
        "no_skill_f1": (2 * prevalence / (1 + prevalence)) if prevalence else None,
        "accuracy": float(np.mean(pred == y_true)) if y_true.size else None,
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "mcc": float(matthews_corrcoef(y_true, pred)) if len(np.unique(y_true)) > 1 else None,
        "balanced_accuracy": (
            float(balanced_accuracy_score(y_true, pred)) if len(np.unique(y_true)) > 1 else None
        ),
        "brier": float(brier_score_loss(y_true, scores)) if len(np.unique(y_true)) > 1 else None,
        "confusion_matrix": confusion_matrix(y_true, pred, labels=[0, 1]).tolist(),
    }
    if len(np.unique(y_true)) > 1:
        out["roc_auc"] = float(roc_auc_score(y_true, scores))
        out["pr_auc"] = float(average_precision_score(y_true, scores))
    else:
        out["roc_auc"] = None
        out["pr_auc"] = None
    return out


def wilson_interval(successes: int, total: int, z: float = 1.96) -> dict:
    if total <= 0:
        return {"low": None, "high": None, "n": 0, "k": successes}
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * np.sqrt(max(p * (1 - p) / total + z * z / (4 * total * total), 0.0)) / denom
    return {
        "low": float(max(0.0, centre - half)),
        "high": float(min(1.0, centre + half)),
        "n": int(total),
        "k": int(successes),
    }


def cluster_bootstrap_ci(
    clusters: list[np.ndarray],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    alpha: float = 0.05,
    method: str = "bca",
) -> dict:
    """Cluster bootstrap over quarters; BCa with a percentile fallback."""
    groups = [np.asarray(group, dtype=float) for group in clusters if len(group)]
    if not groups:
        return {"estimate": None, "low": None, "high": None, "clusters": 0, "method": method}
    all_values = np.concatenate(groups)
    point = float(np.mean(all_values))
    count = len(groups)
    if count < 2:
        return {
            "estimate": point,
            "low": None,
            "high": None,
            "clusters": count,
            "method": "insufficient clusters",
        }

    rng = np.random.default_rng(seed)
    boot = np.empty(resamples)
    for index in range(resamples):
        pick = rng.integers(0, count, count)
        boot[index] = np.mean(np.concatenate([groups[i] for i in pick]))
    lo, hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)], method="linear")
    used = "percentile"

    jack = np.array(
        [np.mean(np.concatenate([g for j, g in enumerate(groups) if j != i]))
         for i in range(count)]
    )
    jack_mean = jack.mean()
    denominator = np.sum((jack_mean - jack) ** 2)
    if method == "bca" and denominator > 0 and np.std(boot) > 0:
        prop = np.clip(np.mean(boot < point), 1.0 / resamples, 1 - 1.0 / resamples)
        z0 = norm.ppf(prop)
        acceleration = np.sum((jack_mean - jack) ** 3) / (6 * denominator ** 1.5)
        z_alpha = norm.ppf(alpha / 2)
        z_one_minus = norm.ppf(1 - alpha / 2)
        adjusted = [
            norm.cdf(
                z0 + (z0 + z) / (1 - acceleration * (z0 + z))
            )
            for z in (z_alpha, z_one_minus)
        ]
        lo, hi = np.percentile(boot, np.array(adjusted) * 100, method="linear")
        used = "bca"

    return {
        "estimate": point,
        "low": float(lo),
        "high": float(hi),
        "clusters": count,
        "resamples": int(resamples),
        "method": used,
        "alpha": alpha,
    }


def _threshold_value(threshold_block: dict, noise: str) -> float:
    try:
        entry = threshold_block[str(noise)]
    except KeyError as exc:
        raise GateError(f"thresholds missing noise stratum {noise!r}") from exc
    return float(entry["threshold"] if isinstance(entry, dict) else entry)


def physics_operating_point(
    trials: pd.DataFrame,
    threshold_block: dict,
    *,
    tolerance_days: float = TIMING_TOLERANCE_DAYS,
    split: str = "test",
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """Detector operating point on one split: FPR, recall, per-depth recovery, CIs.

    Thresholds come from the frozen detector calibration (train+val nulls). This
    function only *scores*; it never recalibrates and refuses non-requested splits.
    """
    present = set(trials["split"].unique())
    if present != {split}:
        raise GateError(f"physics_operating_point expects only '{split}' rows, got {present}")
    required = {
        "snr",
        "noise_condition",
        "injected",
        "delta_true_days",
        "delta_est_days",
        "quarter",
        "requested_depth_ppm",
    }
    missing = required - set(trials.columns)
    if missing:
        raise GateError(f"missing trial columns: {sorted(missing)}")
    # every stratum present in the data must have a calibrated threshold
    require_noise_strata(
        threshold_block.keys(),
        trials["noise_condition"].unique(),
        context="physics operating point",
        allow_extra=True,
    )

    frame = trials.copy()
    frame["threshold_snr"] = [
        _threshold_value(threshold_block, noise) for noise in frame["noise_condition"]
    ]
    frame["detected"] = frame["snr"].astype(float) > frame["threshold_snr"].astype(float)
    frame["timing_error_days"] = (
        frame["delta_est_days"].astype(float) - frame["delta_true_days"].astype(float)
    ).abs()
    injected = frame["injected"].astype(bool)
    frame["recovered"] = injected & frame["detected"] & (
        frame["timing_error_days"] <= tolerance_days
    )
    frame["false_positive"] = (~injected) & frame["detected"]

    def block(subset: pd.DataFrame) -> dict:
        nulls = subset[~subset["injected"].astype(bool)]
        positives = subset[subset["injected"].astype(bool)]
        fp = int(nulls["false_positive"].sum())
        recovered = int(positives["recovered"].sum())
        fpr_clusters = [
            group["false_positive"].to_numpy(dtype=float)
            for _, group in nulls.groupby("quarter")
        ]
        recall_clusters = [
            group["recovered"].to_numpy(dtype=float)
            for _, group in positives.groupby("quarter")
        ]
        by_depth = []
        for depth, group in positives.groupby("requested_depth_ppm"):
            by_depth.append(
                {
                    "requested_depth_ppm": float(depth),
                    "trials": int(len(group)),
                    "recovered": int(group["recovered"].sum()),
                    "fraction": float(group["recovered"].mean()) if len(group) else None,
                    "wilson": wilson_interval(
                        int(group["recovered"].sum()), int(len(group))
                    ),
                }
            )
        return {
            "null_trials": int(len(nulls)),
            "false_positives": fp,
            "fpr": (fp / len(nulls)) if len(nulls) else None,
            "fpr_wilson": wilson_interval(fp, int(len(nulls))),
            "fpr_cluster": cluster_bootstrap_ci(
                fpr_clusters, resamples=resamples, seed=seed
            ),
            "injected_trials": int(len(positives)),
            "recovered": recovered,
            "recall": (recovered / len(positives)) if len(positives) else None,
            "recall_wilson": wilson_interval(recovered, int(len(positives))),
            "recall_cluster": cluster_bootstrap_ci(
                recall_clusters, resamples=resamples, seed=seed
            ),
            "by_depth": sorted(by_depth, key=lambda item: item["requested_depth_ppm"]),
        }

    by_noise = {
        str(noise): block(group)
        for noise, group in frame.groupby("noise_condition")
    }
    return {
        "spec": DETECTOR_REPORT_SPEC,
        "split": split,
        "timing_tolerance_days": float(tolerance_days),
        "thresholds": {
            str(noise): _threshold_value(threshold_block, str(noise))
            for noise in frame["noise_condition"].unique()
        },
        "by_noise": by_noise,
        "pooled": block(frame),
    }


def evaluate_test(
    out_dir: Path,
    *,
    protocol_path: Path,
    trials: pd.DataFrame,
    manifest_dir: Path,
) -> dict:
    """Single, auditable test read. Requires frozen protocol and fitted state.

    The ledger is written *before* any test row is scored, so a crash or a restart
    cannot be used to re-read the test set: the record exists either way.
    """
    protocol, protocol_hash = load_frozen_json(
        protocol_path,
        expected_phase=EXPECTED_PHASE,
        expected_schema=EXPECTED_SCHEMA_VERSION,
    )
    assert_protocol_manifests(protocol, manifest_dir)
    fitted = load_fitted(out_dir, protocol_hash)
    if (out_dir / "test_access.json").is_file():
        raise GateError("test has already been evaluated once (see test_access.json)")

    test = trials[trials["split"] == "test"]
    if test.empty:
        raise GateError("no test rows supplied")
    if set(trials["split"].unique()) - {"test"}:
        raise GateError("evaluate_test accepts test rows only")

    ledger = {
        "status": "started",
        "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "protocol_sha256": protocol_hash,
        "fitted_sha256": fitted["_sha256"],
        "test_rows": int(len(test)),
        "threshold": fitted["threshold"]["threshold"],
        "threshold_scope": fitted["threshold"]["scope"],
        "clusters": int(test["quarter"].nunique()),
    }
    (out_dir / "test_access.json").write_text(
        json.dumps(ledger, indent=2) + "\n", encoding="utf-8"
    )

    model = pickle.loads(
        (out_dir / _safe_model_filename(fitted["model_file"])).read_bytes()
    )
    features = fitted["features"]
    matrix = np.where(
        np.isfinite(test[features].to_numpy(dtype=float)),
        test[features].to_numpy(dtype=float),
        np.asarray(fitted["imputation_medians"], dtype=float),
    )
    scores = model.predict_proba(matrix)[:, 1]
    metrics = detection_metrics(
        test["injected"].to_numpy(dtype=int), scores, fitted["threshold"]["threshold"]
    )
    ledger["status"] = "completed"
    ledger["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (out_dir / "test_access.json").write_text(
        json.dumps(ledger, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "metrics_test.json").write_text(
        json.dumps({"metrics": metrics, "ledger": ledger}, indent=2) + "\n", encoding="utf-8"
    )
    return {"metrics": metrics, "ledger": ledger}


# --- stage 1: campaign (implemented, never executed in Phase 11b) ------------


def _load_window_series(quarter: str, root: Path) -> tuple[np.ndarray, np.ndarray]:
    validate_quarter(quarter)
    path = root / "data" / "processed" / f"kepler_{quarter.lower()}_quality_masked.csv"
    times, flux, _excluded = gen.load_quarter(path)
    return times, flux


def index_windows(windows: list[dict]) -> dict[tuple[str, int], dict]:
    """Key windows by (quarter, window_index); a quarter holds many windows."""
    lookup = {}
    for window in windows:
        quarter = validate_quarter(window.get("quarter"))
        key = (quarter, int(window["window_index"]))
        if key in lookup:
            raise GateError(f"duplicate window key: {key}")
        lookup[key] = window
    return lookup


def run_campaign(
    *,
    manifest_dir: Path,
    out_dir: Path,
    window_days: float,
    split_group: str,
    root: Path | None = None,
    manifest_name: str | None = None,
    windows: list[dict] | None = None,
) -> pd.DataFrame:
    """Generate, inject and detect a campaign split group. Not run in stages 0-1.

    ``windows`` restricts the campaign to an explicit subset (the smoke CLI passes its
    pre-registered quarters); when omitted the full window manifest is used.
    ``split_group='test'`` is refused until the fitted artifact is frozen.
    """
    if split_group not in {"fit", "test"}:
        raise ValueError("split_group must be 'fit' or 'test'")
    if split_group == "test":
        assert_test_generation_allowed(out_dir)

    root = root or gen.project_root()
    if windows is None:
        name = manifest_name or (
            "windows_primary.json" if window_days == 5.0 else "windows_sensitivity.json"
        )
        windows = json.loads((manifest_dir / name).read_text(encoding="utf-8"))["windows"]
    plan = plan_trials(windows, build_protocol(manifest_dir), split_group)

    offsets, _offsets_hash = load_frozen_json(
        manifest_dir / "offsets.json",
        expected_phase=EXPECTED_PHASE,
        expected_schema=EXPECTED_SCHEMA_VERSION,
    )
    table = offsets["by_window_length"][f"{window_days:.1f}"]
    lookup = {
        (validate_quarter(row["quarter"]), row["window_index"]): row["offsets_days"]
        for row in table["draws"]
    }

    by_window = index_windows(windows)
    cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    rows = []
    for record in plan.to_dict(orient="records"):
        window = by_window[(record["quarter"], int(record["window_index"]))]
        if record["quarter"] not in cache:
            cache[record["quarter"]] = _load_window_series(record["quarter"], root)
        times_all, flux_all = cache[record["quarter"]]
        sl = slice(window["start_index"], window["end_index"])
        times = np.asarray(times_all[sl], dtype=float)
        flux = np.asarray(flux_all[sl], dtype=float)
        cleaned, _amplitude = core.remove_published_transit(times, flux, "kepler")
        base = core.apply_noise_condition(cleaned, record["noise_condition"])
        delta = lookup[(record["quarter"], record["window_index"])][record["offset_index"]]
        if record["requested_depth_ppm"] > 0:
            dt = core.phase_offsets(times, "kepler", delta)
            presented = ti.inject_transit(base, dt, record["requested_depth_ppm"])
        else:
            presented = base.copy()
        detection = core.detect(times, presented, "kepler")
        features = time_domain_features(times, presented)
        rows.append(
            {
                **record,
                "delta_true_days": float(delta),
                "snr": float(detection["snr"]),
                "depth_est_ppm": float(detection["depth_ppm"]),
                "sigma_ppm": float(detection["sigma_ppm"]),
                "delta_est_days": float(detection["delta"]),
                **features,
            }
        )
    frame = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_dir / f"trials_{split_group}.csv", index=False)
    return frame


def time_domain_features(times: np.ndarray, flux: np.ndarray) -> dict:
    baseline = float(np.median(flux))
    resid = flux - baseline
    gaps = np.diff(times) > 0.05
    return {
        "min_depth_ppm": float((baseline - float(np.min(flux))) * 1e6),
        "std_ppm": float(np.std(flux) * 1e6),
        "mad_ppm": float(np.median(np.abs(resid)) * 1e6),
        "gap_fraction": float(np.sum(gaps) / max(1, len(times) - 1)),
        "mean_flux": float(np.mean(flux)),
        "n_points": int(len(times)),
    }


MODES = {
    "smoke": {
        "window_days": 5.0,
        "split_groups": ("fit",),
        "quarters": ("Q00", "Q01", "Q04"),
        "note": "train+val only; never reads a test quarter",
    },
    "full": {"window_days": 5.0, "split_groups": ("fit", "test"), "quarters": None, "note": ""},
    "sensitivity": {
        "window_days": 3.0,
        "split_groups": ("fit", "test"),
        "quarters": None,
        "note": "reported separately; never used to pick the primary window length",
    },
}


def describe_mode(mode: str, manifest_dir: Path) -> dict:
    """Resolve a pre-registered campaign mode into trial counts. No execution."""
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")
    spec = MODES[mode]
    name = (
        "windows_primary.json" if spec["window_days"] == 5.0 else "windows_sensitivity.json"
    )
    windows = json.loads((manifest_dir / name).read_text(encoding="utf-8"))["windows"]
    if spec["quarters"]:
        allowed = set(spec["quarters"])
        windows = [w for w in windows if w["quarter"] in allowed]
    protocol = build_protocol(manifest_dir)
    groups = {}
    for group in spec["split_groups"]:
        plan = plan_trials(windows, protocol, group)
        groups[group] = {
            "trials": int(len(plan)),
            "splits": sorted(set(plan["split"])),
            "quarters": sorted(set(plan["quarter"])),
        }
    return {
        "mode": mode,
        "window_days": spec["window_days"],
        "note": spec["note"],
        "groups": groups,
    }


def main() -> None:  # pragma: no cover - CLI glue
    parser = argparse.ArgumentParser(description="Phase 11b stage 0/1 utilities.")
    parser.add_argument("--stage", choices=("plan",), default="plan")
    parser.add_argument("--describe-mode", choices=tuple(MODES), default=None)
    parser.add_argument("--manifest-dir", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    manifest_dir = Path(args.manifest_dir) if args.manifest_dir else (
        gen.project_root() / "reports" / "phase11_generalization"
    )
    if args.describe_mode:
        print(json.dumps(describe_mode(args.describe_mode, manifest_dir), indent=2))
        return
    out_dir = Path(args.out) if args.out else manifest_dir
    hashes = write_stage0(out_dir, manifest_dir)
    print(json.dumps({"written": hashes}, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = [
    "DETECTOR_REPORT_SPEC",
    "TIMING_TOLERANCE_DAYS",
    "GateError",
    "assert_fit_splits",
    "assert_protocol_manifests",
    "assert_test_generation_allowed",
    "build_offsets",
    "build_protocol",
    "build_stage0",
    "calibrate_detector_thresholds",
    "choose_threshold",
    "cluster_bootstrap_ci",
    "detection_metrics",
    "evaluate_test",
    "feature_columns",
    "fit_models",
    "freeze_fitted",
    "load_fitted",
    "physics_operating_point",
    "plan_trials",
    "run_campaign",
    "wilson_interval",
    "write_stage0",
]
