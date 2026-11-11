"""Phase 11 Stage B7: the dedicated real-data fitting entry point (`fit_real`).

This module fits the primary model on the **protocol-designated fit quarters only** and freezes the
same nine-key fitted state B1 produces. It is deliberately separate from the synthetic-only B1 path:
B1's source guard, frame guard and payload contract are untouched, and neither module can reach the
other's allowed rows.

What this module can never do:

* read, list or score sealed test data — no test quarter is loaded, and no ``trials_test.csv``,
  ``test_access.json``, ``test_generation.json`` or ``metrics_test.json`` may be present anywhere
  the fit writes; any frame carrying a test split or a test quarter is refused before features
  are computed;
* generate trials, create campaign markers, or write anything except the frozen fitted artifact;
* run without an explicit fitting authorization whose quarter list equals the frozen fit quarters.

The fit frame mirrors the campaign's fit-split construction (transit removal, noise condition,
coherent injection from the frozen offset draws, matched-filter detection, shared feature builder),
so the L7 and detector calibration pools reproduce the protocol's 42 and 134 nulls per stratum.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd
import transit_injection as ti

from . import core, phase11
from . import generalization as gen
from . import phase11_authz as authz
from . import phase11_b1 as b1
from . import phase11_v2 as v2
from .features import time_domain_features
from .phase11 import GateError
from .phase11_runner import OutputIsolationError, resolve_output_dir

REAL_FIT_SOURCE = authz.FIT_SOURCE
FIT_MISSION = "kepler"
WINDOW_MANIFEST = "windows_primary.json"
WINDOW_DAYS = 5.0
FIT_SPLITS = ("train", "val")
MISSION_REFERENCE = "kepler"
TEST_ARTIFACTS = (
    "trials_test.csv",
    "trials_test.sha256",
    "test_access.json",
    "test_generation.json",
    "metrics_test.json",
)
REQUIRED_FRAME_COLUMNS = (
    "trial_id",
    "quarter",
    "window_index",
    "split",
    "role",
    "requested_depth_ppm",
    "injected",
    "noise_condition",
    "source",
    "delta_true_days",
    "delta_est_days",
    "snr",
    "depth_est_ppm",
    "sigma_ppm",
)


def b7_test_quarters(manifest_dir: Path, effective: Mapping) -> set[str]:
    """Test quarters from the frozen split manifest (never read, only named)."""
    _fit, test = protocol_fit_quarters(manifest_dir, effective)
    return test


def _fit_authorization(
    manifest_dir: Path,
    repo_root: Path,
    effective: Mapping,
    fit_quarters: set[str],
    authorization: authz.AuthorizationRef,
) -> tuple[dict, str]:
    """Bind the hashed OD-2 document to the frozen manifests and the fit quarter set."""
    manifests = v2.validate_manifests(Path(manifest_dir), dict(effective))
    return authz.load_authorization_document(
        authorization,
        protocol_sha256=v2.AUTHORIZED_PROTOCOL_SHA256,
        manifest_hashes=manifests,
        location=authz.DocumentLocation(manifest_dir=Path(manifest_dir), repo_root=Path(repo_root)),
        fit_quarters=fit_quarters,
        test_quarters=b7_test_quarters(manifest_dir, effective),
        required_scope="fit",
    )


def protocol_fit_quarters(manifest_dir: Path, effective: Mapping) -> tuple[set[str], set[str]]:
    """Return (fit, test) quarters from the hash-verified frozen split manifest."""
    v2.validate_manifests(Path(manifest_dir), dict(effective))
    payload = json.loads((Path(manifest_dir) / "split.json").read_text(encoding="utf-8"))
    quarters = payload.get("quarters")
    if not isinstance(quarters, Mapping):
        raise GateError("the frozen split manifest has no quarters mapping")
    fit, test = set(), set()
    for quarter, meta in quarters.items():
        if not isinstance(meta, Mapping):
            raise GateError(f"split manifest entry for {quarter!r} is not a mapping")
        split = meta.get("split")
        if split in FIT_SPLITS:
            fit.add(str(quarter))
        elif split == "test":
            test.add(str(quarter))
        else:
            raise GateError(f"split manifest entry for {quarter!r} has split {split!r}")
    if not fit or not test:
        raise GateError("the frozen split manifest must declare both fit and test quarters")
    overlap = sorted(fit & test)
    if overlap:
        raise GateError(f"quarters declared as both fit and test: {overlap}")
    return fit, test


def _validate_fit_window(window: Mapping, fit_quarters: set[str], test_quarters: set[str]) -> None:
    quarter = str(window.get("quarter"))
    split = window.get("split")
    if quarter in test_quarters:
        raise GateError(f"window {quarter} belongs to a test quarter; refusing before any read")
    if quarter not in fit_quarters:
        raise GateError(f"window quarter {quarter!r} is not a frozen fit quarter")
    if split not in FIT_SPLITS:
        raise GateError(f"window {quarter}/{window.get('window_index')} has split {split!r}")
    if window.get("role") not in ("null", "injection"):
        raise GateError(f"window {quarter}/{window.get('window_index')} has a foreign role")
    start, end = window.get("start_index"), window.get("end_index")
    if not isinstance(start, int) or not isinstance(end, int) or start >= end:
        raise GateError(f"window {quarter}/{window.get('window_index')} has an invalid slice")


def _classify_window(window: Mapping, fit_quarters: set[str], test_quarters: set[str]) -> bool:
    """True means the window belongs to the fit path; test windows are excluded, never loaded."""
    quarter = str(window.get("quarter"))
    split = window.get("split")
    if quarter in test_quarters:
        if split != "test":
            raise GateError(f"window {quarter} is in a test quarter but declares split {split!r}")
        return False
    if quarter not in fit_quarters:
        raise GateError(f"window quarter {quarter!r} is not a frozen fit quarter")
    if split not in FIT_SPLITS:
        raise GateError(f"window {quarter}/{window.get('window_index')} has split {split!r}")
    _validate_fit_window(window, fit_quarters, test_quarters)
    return True


def fit_windows(
    manifest_dir: Path, effective: Mapping, fit_quarters: set[str], test_quarters: set[str]
) -> list[dict]:
    """Load the frozen primary-window manifest and keep only validated fit windows."""
    payload = json.loads((Path(manifest_dir) / WINDOW_MANIFEST).read_text(encoding="utf-8"))
    windows = payload.get("windows")
    if not isinstance(windows, list) or not windows:
        raise GateError("the frozen window manifest has no windows")
    if float(payload.get("window_days")) != WINDOW_DAYS:
        raise GateError("fit_real fits the primary 5-day campaign only")
    kept = [window for window in windows if _classify_window(window, fit_quarters, test_quarters)]
    if not kept:
        raise GateError("the frozen window manifest holds no fit windows")
    quarters = {str(window["quarter"]) for window in kept}
    if quarters & test_quarters:
        raise GateError("a test quarter survived window classification; refusing")
    return kept


def assert_plan_fit_only(
    plan: pd.DataFrame, fit_quarters: set[str], test_quarters: set[str]
) -> None:
    """Refuse any test row, foreign quarter, role or duplicate identity before data is read."""
    splits = {str(value) for value in plan["split"].unique()}
    if "test" in splits:
        raise GateError("the fit plan contains test rows; refusing before any quarter is read")
    unexpected = sorted(splits - set(FIT_SPLITS))
    if unexpected:
        raise GateError(f"the fit plan has unexpected splits {unexpected}")
    quarters = {str(value) for value in plan["quarter"].unique()}
    leaked = sorted(quarters & test_quarters)
    if leaked:
        raise GateError(f"the fit plan touches test quarters {leaked}")
    foreign = sorted(quarters - fit_quarters)
    if foreign:
        raise GateError(f"the fit plan touches non-fit quarters {foreign}")
    roles = {str(value) for value in plan["role"].unique()}
    if roles - {"null_window", "injection"}:
        raise GateError(f"the fit plan has foreign roles {sorted(roles)}")
    if bool(plan["trial_id"].duplicated().any()):
        raise GateError("the fit plan has duplicate trial ids")


def _integrity_entry(quarter: str, meta: object) -> dict:
    """Validate one pinned integrity record from the frozen split manifest."""
    if not isinstance(meta, Mapping):
        raise GateError(f"split manifest entry for {quarter!r} is not a mapping")
    digest = meta.get("sha256")
    if not isinstance(digest, str) or v2.SHA256_PATTERN.fullmatch(digest.lower()) is None:
        raise GateError(f"split manifest entry for {quarter!r} has no valid sha256 digest")
    entry = {"sha256": digest.lower()}
    if "rows" in meta:
        rows = meta["rows"]
        if isinstance(rows, bool) or not isinstance(rows, int) or rows <= 0:
            raise GateError(f"split manifest entry for {quarter!r} has an invalid row count")
        entry["rows"] = rows
    return entry


def quarter_integrity(
    manifest_dir: Path, effective: Mapping, fit_quarters: set[str]
) -> dict[str, dict]:
    """Pinned SHA-256 (and row count where specified) for every frozen fit quarter."""
    v2.validate_manifests(Path(manifest_dir), dict(effective))
    payload = json.loads((Path(manifest_dir) / "split.json").read_text(encoding="utf-8"))
    quarters = payload.get("quarters")
    if not isinstance(quarters, Mapping):
        raise GateError("the frozen split manifest has no quarters mapping")
    integrity = {}
    for quarter in sorted(fit_quarters):
        if quarter not in quarters:
            raise GateError(f"split manifest has no integrity record for {quarter!r}")
        integrity[quarter] = _integrity_entry(quarter, quarters[quarter])
    return integrity


def _contained_quarter_path(quarter: str, root: Path) -> Path:
    """Build the input path and refuse symlink or containment escapes."""
    root_resolved = Path(root).resolve()
    data_root = (root_resolved / "data" / "processed").resolve()
    if not data_root.is_relative_to(root_resolved):
        raise GateError(
            f"data root {data_root} escapes the permitted repository root {root_resolved}"
        )
    path = data_root / f"kepler_{quarter.lower()}_quality_masked.csv"
    if path.is_symlink():
        raise GateError(f"refusing to follow the symlinked quarter file {path.name}")
    resolved = path.resolve()
    if resolved.parent != data_root:
        raise GateError(f"quarter {quarter} resolves outside the permitted data root")
    return resolved


def _expected_integrity(quarter: str, integrity: Mapping[str, Mapping] | None) -> dict:
    if integrity is None:
        raise GateError("load_fit_series requires pinned integrity metadata")
    expected = integrity.get(quarter)
    if expected is None:
        raise GateError(f"no pinned integrity metadata for the fit quarter {quarter}")
    return dict(expected)


def _verified_series(
    quarter: str, resolved: Path, expected: Mapping | None
) -> tuple[np.ndarray, np.ndarray, int]:
    if not resolved.is_file():
        raise GateError(f"fit quarter file is missing: {resolved.name}")
    digest = v2.sha256_file(resolved)
    if expected is None or digest != expected["sha256"]:
        pin = "missing" if expected is None else expected["sha256"]
        raise GateError(
            f"{resolved.name} hash {digest} does not match the frozen split manifest {pin}"
        )
    times, flux, excluded = gen.load_quarter(resolved)
    return np.asarray(times, dtype=float), np.asarray(flux, dtype=float), int(excluded)


def _check_pinned_rows(name: str, expected: Mapping | None, points: int, excluded: int) -> None:
    if expected is None or "rows" not in expected:
        return
    observed = int(points) + int(excluded)
    if observed != expected["rows"]:
        raise GateError(
            f"{name} has {observed} rows but the frozen split manifest pins {expected['rows']}"
        )


def load_verified_quarter(
    quarter: str,
    root: Path,
    allowed_quarters: set[str],
    *,
    integrity: Mapping[str, Mapping] | None = None,
    label: str = "fit",
) -> tuple[np.ndarray, np.ndarray]:
    """Load one frozen fit quarter after integrity and containment checks.

    The quarter file must match the digest pinned in the frozen split manifest, its row count must
    match where pinned, and its resolved path must sit directly in the resolved data root.
    """
    phase11.validate_quarter(quarter)
    if quarter not in allowed_quarters:
        raise GateError(f"quarter {quarter!r} is not a frozen {label} quarter; refusing to load it")
    expected = _expected_integrity(quarter, integrity)
    resolved = _contained_quarter_path(quarter, root)
    times, flux, excluded = _verified_series(quarter, resolved, expected)
    if times.size == 0 or times.size != flux.size:
        raise GateError(f"quarter {quarter} did not yield a usable series")
    if not (np.isfinite(times).all() and np.isfinite(flux).all()):
        raise GateError(f"quarter {quarter} contains non-finite values after loading")
    _check_pinned_rows(resolved.name, expected, times.size, excluded)
    return times, flux


def load_fit_series(
    quarter: str,
    root: Path,
    fit_quarters: set[str],
    *,
    integrity: Mapping[str, Mapping] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit-quarter reader; see :func:`load_verified_quarter` for the shared contract."""
    return load_verified_quarter(quarter, root, fit_quarters, integrity=integrity, label="fit")


# --- frame construction ------------------------------------------------------


def _offset_lookup(offsets: Mapping) -> dict[tuple[str, int], list[float]]:
    table = offsets["by_window_length"][f"{WINDOW_DAYS:.1f}"]
    return {
        (str(row["quarter"]), int(row["window_index"])): list(row["offsets_days"])
        for row in table["draws"]
    }


def _rows_from_plan(
    plan: pd.DataFrame,
    windows_by_key: Mapping[tuple[str, int], Mapping],
    offsets: Mapping[tuple[str, int], Sequence[float]],
    *,
    fit_quarters: set[str],
    root: Path,
    integrity: Mapping[str, Mapping] | None = None,
) -> list[dict]:
    cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    rows = []
    for record in plan.to_dict(orient="records"):
        quarter = str(record["quarter"])
        window = windows_by_key[(quarter, int(record["window_index"]))]
        if quarter not in cache:
            cache[quarter] = load_fit_series(quarter, root, fit_quarters, integrity=integrity)
        times_all, flux_all = cache[quarter]
        times = np.asarray(times_all[window["start_index"] : window["end_index"]], dtype=float)
        flux = np.asarray(flux_all[window["start_index"] : window["end_index"]], dtype=float)
        cleaned, _amplitude = core.remove_published_transit(times, flux, FIT_MISSION)
        base = core.apply_noise_condition(cleaned, record["noise_condition"])
        delta = float(offsets[(quarter, int(record["window_index"]))][record["offset_index"]])
        if float(record["requested_depth_ppm"]) > 0:
            phase = core.phase_offsets(times, FIT_MISSION, delta)
            presented = ti.inject_transit(base, phase, float(record["requested_depth_ppm"]))
        else:
            presented = base.copy()
        detection = core.detect(times, presented, FIT_MISSION)
        rows.append(
            {
                **record,
                "source": REAL_FIT_SOURCE,
                "delta_true_days": delta,
                "snr": float(detection["snr"]),
                "depth_est_ppm": float(detection["depth_ppm"]),
                "sigma_ppm": float(detection["sigma_ppm"]),
                "delta_est_days": float(detection["delta"]),
                **time_domain_features(times, presented),
            }
        )
    return rows


def _assert_frame_vocabulary(frame: pd.DataFrame, fit_quarters: set[str]) -> None:
    splits = {str(value) for value in frame["split"].unique()}
    if "test" in splits:
        raise GateError("the real fit frame contains test rows; refusing before fitting")
    if splits - set(FIT_SPLITS):
        raise GateError(f"the real fit frame has unexpected splits {sorted(splits)}")
    quarters = {str(value) for value in frame["quarter"].unique()}
    foreign = sorted(quarters - fit_quarters)
    if foreign:
        raise GateError(f"the real fit frame touches non-fit quarters {foreign}")
    sources = sorted({str(value) for value in frame["source"].unique()})
    if sources != [REAL_FIT_SOURCE]:
        raise GateError(
            f"the real fit frame must carry the {REAL_FIT_SOURCE!r} tag only, got {sources}"
        )
    roles = {str(value) for value in frame["role"].unique()}
    if roles - {"null_window", "injection"}:
        raise GateError(f"the real fit frame has foreign roles {sorted(roles)}")


def _assert_frame_labels(frame: pd.DataFrame) -> None:
    expected = frame["requested_depth_ppm"] > 0
    if not bool((frame["injected"].astype(bool) == expected).all()):
        raise GateError("label invariant violated: injected != (requested_depth_ppm > 0)")
    nulls = frame[frame["role"] == "null_window"]
    if nulls[nulls["split"] == "val"].empty:
        raise GateError("validation nulls are required to calibrate the threshold")
    if bool(frame["trial_id"].duplicated().any()):
        raise GateError("the real fit frame has duplicate trial ids")


def assert_fit_frame(frame: object, effective: Mapping, fit_quarters: set[str]) -> list[str]:
    """Final guard on a real fit frame: fit quarters only, real-fit tag only, no test anything."""
    if not isinstance(frame, pd.DataFrame):
        raise GateError("the real fit path accepts a DataFrame of real fit rows only")
    if frame.empty:
        raise GateError("the real fit frame is empty")
    missing = [column for column in REQUIRED_FRAME_COLUMNS if column not in frame.columns]
    if missing:
        raise GateError(f"the real fit frame is missing required columns {missing}")
    _assert_frame_vocabulary(frame, fit_quarters)
    _assert_frame_labels(frame)
    columns = phase11.feature_columns(dict(effective), _primary_model(effective))
    absent = [column for column in columns if column not in frame.columns]
    if absent:
        raise GateError(f"the real fit frame is missing feature columns {absent}")
    phase11.assert_fit_splits(frame, dict(effective))
    return columns


def _primary_model(effective: Mapping) -> str:
    features_block = effective.get("features")
    if not isinstance(features_block, Mapping):
        raise GateError("the effective protocol has no features block")
    model_id = features_block.get("primary_model")
    if not isinstance(model_id, str) or not model_id:
        raise GateError("the effective protocol names no primary model")
    return model_id


def build_fit_frame(
    *,
    effective: Mapping,
    manifest_dir: Path,
    root: Path,
    authorization: authz.AuthorizationRef,
    model_id: str | None = None,
) -> pd.DataFrame:
    """Build real fit rows from frozen fit quarters only. No test path is ever constructed."""
    b1.assert_approved_protocol(effective, v2.AUTHORIZED_PROTOCOL_SHA256)
    fit_quarters, test_quarters = protocol_fit_quarters(manifest_dir, effective)
    _fit_authorization(manifest_dir, Path(root), effective, fit_quarters, authorization)
    windows = fit_windows(manifest_dir, effective, fit_quarters, test_quarters)
    plan = phase11.plan_trials(windows, dict(effective), "fit")
    assert_plan_fit_only(plan, fit_quarters, test_quarters)
    offsets, _offsets_hash = v2.load_frozen_offsets(Path(manifest_dir), dict(effective))
    integrity = quarter_integrity(manifest_dir, effective, fit_quarters)
    frame = pd.DataFrame(
        _rows_from_plan(
            plan,
            {(str(window["quarter"]), int(window["window_index"])): window for window in windows},
            _offset_lookup(offsets),
            fit_quarters=fit_quarters,
            root=Path(root),
            integrity=integrity,
        )
    )
    assert_fit_frame(frame, effective, fit_quarters)
    if model_id is not None:
        phase11.feature_columns(dict(effective), model_id)
    return frame


# --- gated fit and freeze ----------------------------------------------------


FIT_SOURCE_FILES = (
    "features.py",
    "phase11_authz.py",
    "phase11_b1.py",
    "phase11_b2a.py",
    "phase11_b7.py",
    "phase11_runner.py",
    "phase11_v2.py",
    "safeguards.py",
    "test_access.py",
)


def _fit_source_paths() -> list[Path]:
    source_dir = Path(__file__).resolve().parent
    paths = [source_dir / name for name in FIT_SOURCE_FILES]
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise GateError(f"fit source artifacts are missing: {missing}")
    return paths


def capture_fit_provenance(manifest_dir: Path, effective: Mapping, repo_root: Path) -> dict:
    """Capture provenance from the repository itself; never trust a caller-supplied block."""
    manifest_hashes = v2.validate_manifests(Path(manifest_dir), dict(effective))
    _offsets, offsets_sha256 = v2.load_frozen_offsets(Path(manifest_dir), dict(effective))
    provenance = v2.capture_provenance(
        Path(repo_root),
        source_paths=_fit_source_paths(),
        protocol_sha256=v2.AUTHORIZED_PROTOCOL_SHA256,
        manifest_hashes=manifest_hashes,
        offsets_sha256=offsets_sha256,
    )
    v2.require_clean_tree(provenance)
    return provenance


def _assert_no_test_exposure(out_dir: Path) -> None:
    """Resolve the output path and its parent first, so a symlink cannot hide an exposure."""
    for candidate in (Path(out_dir), Path(out_dir).parent):
        try:
            base = candidate.resolve()
        except OSError as exc:
            raise GateError(f"output path {candidate} cannot be resolved safely: {exc}") from exc
        if base.exists() and not base.is_dir():
            raise OutputIsolationError(f"output path {base} exists and is not a directory")
        present = [name for name in TEST_ARTIFACTS if (base / name).exists()]
        if present:
            raise GateError(
                f"fit_real must never run next to sealed test artifacts; {base} holds {present}"
            )


def fit_real(
    *,
    effective: Mapping,
    manifest_dir: Path,
    repo_root: Path,
    out_dir: Path,
    authorization: authz.AuthorizationRef,
    model_id: str | None = None,
) -> dict:
    """Fit and freeze the real fitted state. No marker, trial or test access is created."""
    b1.assert_approved_protocol(effective, v2.AUTHORIZED_PROTOCOL_SHA256)
    fit_quarters, _test_quarters = protocol_fit_quarters(manifest_dir, effective)
    document, authorization_digest = _fit_authorization(
        manifest_dir, repo_root, effective, fit_quarters, authorization
    )
    _assert_no_test_exposure(out_dir)
    _assert_no_test_exposure(manifest_dir)
    out = resolve_output_dir(Path(out_dir), manifest_dir=manifest_dir, repo_root=repo_root)
    provenance = capture_fit_provenance(manifest_dir, effective, repo_root)
    binding = authz.authorization_binding(document, authorization_digest)
    bound_provenance = {**provenance, "authorization": binding}

    frame = build_fit_frame(
        effective=effective,
        manifest_dir=manifest_dir,
        root=Path(repo_root),
        authorization=authorization,
        model_id=model_id,
    )
    # Defence in depth: the frame is re-asserted here so a replacement or patched builder cannot
    # hand the fitter a test row.
    assert_fit_frame(frame, effective, fit_quarters)
    resolved_model = model_id or _primary_model(effective)
    fitted = phase11.fit_models(frame, dict(effective), resolved_model)
    thresholds = _calibrate_l7(effective, frame, fitted, resolved_model)
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
    missing = [key for key in b1.FITTED_PAYLOAD_KEYS if key not in payload]
    if missing:  # pragma: no cover - the literal above is the contract
        raise GateError(f"fitted payload is missing {missing}")

    artifacts = v2.freeze_fitted_v21(
        out,
        fitted=payload,
        model=fitted["model"],
        trials=frame,
        protocol=dict(effective),
        protocol_hash=v2.AUTHORIZED_PROTOCOL_SHA256,
        provenance=bound_provenance,
    )
    reloaded = v2.load_fitted_v21(out, v2.AUTHORIZED_PROTOCOL_SHA256)
    return {
        "mode": "real_fit",
        "model_id": resolved_model,
        "out_dir": str(out),
        "rows": int(len(frame)),
        "fit_quarters": sorted(fit_quarters),
        "train_rows": int(fitted["train_rows"]),
        "val_rows": int(fitted["val_rows"]),
        "calibration_nulls": {
            "l7": {
                stratum: int(
                    len(
                        frame[
                            (frame["split"] == "val")
                            & (frame["role"] == "null_window")
                            & (frame["noise_condition"] == stratum)
                        ]
                    )
                )
                for stratum in thresholds
            },
            "detector": {
                stratum: int(entry.get("n", 0)) for stratum, entry in detector_thresholds.items()
            },
        },
        "artifacts": artifacts,
        "thresholds": v2.stratum_table(thresholds),
        "fitted_sha256": reloaded["_sha256"],
        "authorization": binding,
    }


def _calibrate_l7(effective: Mapping, frame: pd.DataFrame, fitted: Mapping, model_id: str) -> dict:
    calibration = b1._calibration_scores(frame, fitted)
    return v2.calibrate_thresholds_v21(
        calibration,
        dict(effective),
        score_column=b1.SCORE_COLUMN,
        splits=FIT_SPLITS[1:],
        role="null_window",
        floor=effective["thresholds"]["fitted_models"]["floor_snr"],
        score_supremum=1.0,
        context=f"B7|{model_id}",
    )
