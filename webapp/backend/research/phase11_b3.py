"""Phase 11 Stage B3: test evaluation behind the one-shot access claim (design §5.8, §5.4).

Synthetic-only evaluation of the frozen fitted state against the generated test artifact. The
evaluator reads trials only through :func:`phase11_runner.load_authorized_trials`, never through
a caller-supplied DataFrame, and it claims access **before** the first read, so a re-run, an
interrupted run or a concurrent process is refused rather than silently re-evaluating.

Both operating points come from frozen state, never from test data:

* L7 uses the per-stratum score thresholds frozen by B1 from validation nulls;
* the physics comparator uses the detector thresholds B1 froze from train+val nulls.

Reporting follows the protocol: ``fpr_report`` for trial-level false-positive rates (never
described as cluster-adjusted), Wilson intervals for recall, and ``paired_comparison`` per noise
stratum combined with ``combine_confirmatory`` (intersection-union). With the minimum meaningful
difference unset the best attainable status is ``descriptive_only``; a practical-superiority
claim is never produced.

Per design §5.4 this module also implements the G12 refusal audit: every refused gate writes a
durable record naming the gate, the protocol hash, the configuration hash and the timestamp, in
a directory outside the protected frozen tree.

Scope note: the protocol's frozen denominator literals (76 nulls and 72 injections per depth per
stratum) are absolutes of the real campaign; a synthetic fixture cannot meet them, so B3 enforces
the protocol's ``insufficient_data`` minima instead and reports the observed denominators. The
literal-denominator consistency check remains a requirement of the real-campaign stage.
"""

from __future__ import annotations

import json
import os
import pickle
import time
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from . import phase11, safeguards, test_access
from . import phase11_authz as authz
from . import phase11_b1 as b1
from . import phase11_b2 as b2
from . import phase11_b7_generate as b7g
from . import phase11_runner as runner
from . import phase11_v2 as v2
from .phase11 import GateError
from .phase11_b2a import SOURCE as SYNTHETIC_SOURCE
from .phase11_runner import IntegrityError, OutputIsolationError, load_authorized_trials

MODE_SYNTHETIC = b1.MODE_SYNTHETIC
EVALUATOR_NAME = "phase11-v2-b3"
TEST_SPLIT = "test"
METRICS_FILENAME = "metrics_test.json"
REFUSAL_DIRNAME = "phase11_refusals"
TIMING_TOLERANCE_DAYS = phase11.TIMING_TOLERANCE_DAYS
MIN_TEST_CLUSTERS = 3
MIN_TEST_NULLS_PER_STRATUM = 30
MIN_TEST_INJECTIONS_PER_DEPTH_PER_STRATUM = 20
REQUIRED_TRIAL_COLUMNS = (
    "trial_id",
    "quarter",
    "split",
    "role",
    "injected",
    "noise_condition",
    "requested_depth_ppm",
    "delta_true_days",
    "delta_est_days",
    "snr",
    "source",
)


# --- G12 refusal audit -------------------------------------------------------


def configuration_hash(effective: object) -> str | None:
    """Deterministic digest of the resolved configuration, for refusal records."""
    if not isinstance(effective, Mapping):
        return None
    try:
        payload = json.dumps(dict(effective), sort_keys=True, default=str).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return v2.sha256_bytes(payload)


def default_audit_dir(repo_root: Path) -> Path:
    """Production convention for the G12 trail: outside the frozen manifest tree."""
    return Path(repo_root) / "reports" / REFUSAL_DIRNAME


def _resolve_audit_dir(audit_dir: Path, *, manifest_dir: Path, repo_root: Path) -> Path:
    resolved = Path(audit_dir).resolve()
    frozen = Path(manifest_dir).resolve()
    if resolved == frozen or resolved.is_relative_to(frozen):
        raise GateError(
            f"refusal audit directory {resolved} is inside the frozen manifest tree {frozen}; "
            "the audit trail must live outside the protected tree"
        )
    try:
        safeguards.assert_not_protected_directory(
            resolved, root=Path(repo_root).resolve(), purpose="B3 refusal audit"
        )
    except safeguards.SafeguardError as exc:
        raise GateError(str(exc)) from exc
    if resolved.exists() and not resolved.is_dir():
        raise GateError(f"refusal audit path {resolved} exists and is not a directory")
    return resolved


def record_refusal(
    audit_dir: Path,
    *,
    manifest_dir: Path,
    repo_root: Path,
    gate: str,
    message: str,
    effective: object,
    campaign: Path | None = None,
    fitted_sha256: str | None = None,
) -> Path:
    """Persist one refusal record; a refused attempt must leave a durable trace."""
    resolved = _resolve_audit_dir(audit_dir, manifest_dir=manifest_dir, repo_root=repo_root)
    recorded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record = {
        "stage": "B3",
        "evaluator": EVALUATOR_NAME,
        "gate": str(gate),
        "message": str(message),
        "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256,
        "configuration_sha256": configuration_hash(effective),
        "campaign_dir": None if campaign is None else str(Path(campaign)),
        "fitted_sha256": fitted_sha256,
        "recorded_at": recorded_at,
        "schema_version": 1,
    }
    name = f"refusal-{recorded_at.replace(':', '').replace('-', '')}-{os.urandom(6).hex()}.json"
    path = resolved / name
    data = (json.dumps(record, indent=2) + "\n").encode("utf-8")
    try:
        resolved.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except OSError as exc:
        raise GateError(f"could not write the refusal record in {resolved}: {exc}") from exc
    try:
        os.write(descriptor, data)
    except OSError as exc:
        raise GateError(f"could not write the refusal record {path.name}: {exc}") from exc
    finally:
        os.close(descriptor)
    return path


# --- input gates -------------------------------------------------------------


def require_detector_table(fitted: Mapping) -> dict[str, float]:
    """The physics comparator's per-stratum thresholds must be frozen, never recalibrated."""
    table = fitted.get("detector_thresholds")
    if not isinstance(table, Mapping) or not table:
        raise GateError(
            "frozen fitted state carries no detector_thresholds table; refusing to calibrate "
            "the comparator from test data"
        )
    validated: dict[str, float] = {}
    for stratum, entry in table.items():
        if not isinstance(entry, Mapping) or "threshold" not in entry:
            raise GateError(f"detector threshold entry for {stratum!r} has no threshold value")
        value = float(entry["threshold"])
        if not np.isfinite(value):
            raise GateError(f"detector threshold for {stratum!r} is not finite")
        validated[str(stratum)] = value
    return validated


def require_score_table(fitted: Mapping) -> dict[str, float]:
    """Validate the frozen payload shape B3 consumes and return the L7 threshold table."""
    features = fitted.get("features")
    if not isinstance(features, list) or not features:
        raise GateError("frozen fitted state has no feature list")
    medians = fitted.get("imputation_medians")
    if not isinstance(medians, list) or len(medians) != len(features):
        raise GateError("frozen fitted state has imputation medians inconsistent with features")
    if not isinstance(fitted.get("model_file"), str):
        raise GateError("frozen fitted state has no model file reference")
    table = fitted.get("thresholds")
    if not isinstance(table, Mapping) or not table:
        raise GateError("frozen fitted state carries no L7 threshold table")
    validated: dict[str, float] = {}
    for stratum, entry in table.items():
        if not isinstance(entry, Mapping) or "threshold" not in entry:
            raise GateError(f"L7 threshold entry for {stratum!r} has no threshold value")
        value = float(entry["threshold"])
        if not np.isfinite(value):
            raise GateError(f"L7 threshold for {stratum!r} is not finite")
        validated[str(stratum)] = value
    return validated


def _artifact_kind(frame: pd.DataFrame, real_authorization) -> str:
    sources = sorted({str(value) for value in frame["source"].unique()})
    if sources == [SYNTHETIC_SOURCE]:
        return "synthetic"
    if sources != [b7g.SOURCE]:
        raise GateError(
            f"B3 evaluates the synthetic generator or an authorized real artifact only, got "
            f"sources {sources}"
        )
    if real_authorization is None:
        raise GateError(
            "the artifact carries real campaign trials; an authorization document is required"
        )
    if "campaign_id" not in frame.columns:
        raise GateError("the real artifact has no campaign_id column")
    campaigns = sorted({str(value) for value in frame["campaign_id"].unique()})
    if campaigns != [real_authorization.campaign_id]:
        raise GateError(
            f"artifact campaign ids {campaigns} do not match {real_authorization.campaign_id!r}"
        )
    return "real"


def _assert_frame_rows(frame: pd.DataFrame, fitted: Mapping) -> list[str]:
    if bool(frame["trial_id"].duplicated().any()):
        raise GateError("test artifact has duplicate trial ids; pairing is undefined")
    for column in ("quarter", "noise_condition", "role"):
        if frame[column].isna().any():
            raise GateError(f"test artifact has null values in {column!r}")
    strata = sorted({str(value) for value in frame["noise_condition"].unique()})
    undeclared = [stratum for stratum in strata if stratum not in fitted["thresholds"]]
    if undeclared:
        raise GateError(f"test artifact strata {undeclared} have no frozen L7 threshold")
    return strata


def assert_test_trials(
    frame: object,
    fitted: Mapping,
    *,
    real_authorization: authz.AuthorizationRef | None = None,
) -> dict:
    """Refuse anything but the synthetic artifact or an authorized real one."""
    if not isinstance(frame, pd.DataFrame):
        raise GateError("the evaluator accepts the generated trial artifact only")
    if frame.empty:
        raise GateError("generated test artifact is empty")
    missing = [column for column in REQUIRED_TRIAL_COLUMNS if column not in frame.columns]
    if missing:
        raise GateError(f"test artifact is missing required columns {missing}")
    splits = {str(value) for value in frame["split"].unique()}
    if splits != {TEST_SPLIT}:
        raise GateError(f"B3 evaluates test-split rows only, got splits {sorted(splits)}")
    kind = _artifact_kind(frame, real_authorization)
    strata = _assert_frame_rows(frame, fitted)
    return {"strata": strata, "rows": int(len(frame)), "kind": kind}


# --- scoring -----------------------------------------------------------------


def _scores(frame: pd.DataFrame, fitted: Mapping, model) -> np.ndarray:
    kept = list(fitted["features"])
    medians = np.asarray(fitted["imputation_medians"], dtype=float)
    matrix = frame[kept].to_numpy(dtype=float)
    filled = np.where(np.isfinite(matrix), matrix, medians)
    return np.asarray(model.predict_proba(filled)[:, 1], dtype=float)


def _mark_detections(
    frame: pd.DataFrame, thresholds: Mapping[str, float], *, column: str, prefix: str
) -> pd.DataFrame:
    out = frame.copy()
    strata = out["noise_condition"].astype(str)
    missing = sorted(set(strata.unique()) - set(thresholds))
    if missing:
        raise GateError(f"no frozen threshold for strata {missing}")
    limits = strata.map(lambda name: float(thresholds[name])).to_numpy(dtype=float)
    detected = out[column].to_numpy(dtype=float) > limits
    timing = (out["delta_est_days"].astype(float) - out["delta_true_days"].astype(float)).abs()
    injected = out["injected"].astype(bool)
    out[f"{prefix}_detected"] = detected
    out[f"{prefix}_timing_error_days"] = timing
    out[f"{prefix}_recovered"] = injected & detected & (timing <= TIMING_TOLERANCE_DAYS)
    out[f"{prefix}_false_positive"] = (~injected) & detected
    return out


def _load_model(campaign: Path, fitted: Mapping):
    path = campaign / str(fitted["model_file"])
    if not path.is_file():
        raise GateError(f"frozen model file is missing: {path.name}")
    try:
        return pickle.loads(path.read_bytes())
    except (OSError, pickle.UnpicklingError, EOFError) as exc:
        raise GateError(f"frozen model file is unreadable: {exc}") from exc


def _score_frame(
    frame: pd.DataFrame,
    fitted: Mapping,
    *,
    campaign: Path,
    l7_thresholds: Mapping[str, float],
    detector_thresholds: Mapping[str, float],
) -> pd.DataFrame:
    model = _load_model(campaign, fitted)
    scored = frame.copy()
    scored["l7_score"] = _scores(scored, fitted, model)
    scored = _mark_detections(scored, l7_thresholds, column="l7_score", prefix="l7")
    return _mark_detections(scored, detector_thresholds, column="snr", prefix="physics")


def _recall(recovered: int, injections: int) -> dict:
    return {
        "recovered": int(recovered),
        "injections": int(injections),
        "value": (recovered / injections) if injections else None,
        "wilson": v2.wilson_interval(int(recovered), int(injections)),
    }


def _insufficiency(group: pd.DataFrame) -> list[str]:
    """Protocol ``insufficient_data`` gates for one stratum; any hit means not evaluated."""
    reasons: list[str] = []
    nulls = group[~group["injected"].astype(bool)]
    positives = group[group["injected"].astype(bool)]
    clusters = int(group["quarter"].nunique())
    if clusters < MIN_TEST_CLUSTERS:
        reasons.append(f"fewer than {MIN_TEST_CLUSTERS} test clusters ({clusters})")
    if len(nulls) < MIN_TEST_NULLS_PER_STRATUM:
        reasons.append(
            f"{len(nulls)} null trials < {MIN_TEST_NULLS_PER_STRATUM} required per stratum"
        )
    for depth, depth_group in positives.groupby("requested_depth_ppm"):
        if len(depth_group) < MIN_TEST_INJECTIONS_PER_DEPTH_PER_STRATUM:
            reasons.append(
                f"{len(depth_group)} injections at {float(depth)} ppm "
                f"< {MIN_TEST_INJECTIONS_PER_DEPTH_PER_STRATUM} required"
            )
    return reasons


def _stratum_report(stratum_frame: pd.DataFrame) -> dict:
    nulls = stratum_frame[~stratum_frame["injected"].astype(bool)]
    positives = stratum_frame[stratum_frame["injected"].astype(bool)]
    by_depth = [
        {
            "requested_depth_ppm": float(depth),
            "injections": int(len(group)),
            "l7_recovered": int(group["l7_recovered"].sum()),
            "physics_recovered": int(group["physics_recovered"].sum()),
        }
        for depth, group in positives.groupby("requested_depth_ppm")
    ]
    return {
        "nulls": int(len(nulls)),
        "injections": int(len(positives)),
        "clusters": int(stratum_frame["quarter"].nunique()),
        "fpr": {
            "l7": v2.fpr_report(int(nulls["l7_false_positive"].sum()), int(len(nulls))),
            "physics": v2.fpr_report(int(nulls["physics_false_positive"].sum()), int(len(nulls))),
        },
        "recall": {
            "l7": _recall(int(positives["l7_recovered"].sum()), int(len(positives))),
            "physics": _recall(int(positives["physics_recovered"].sum()), int(len(positives))),
        },
        "by_depth": sorted(by_depth, key=lambda item: item["requested_depth_ppm"]),
        "timing_tolerance_days": float(TIMING_TOLERANCE_DAYS),
    }


def _paired_frame(stratum_frame: pd.DataFrame) -> pd.DataFrame:
    positives = stratum_frame[stratum_frame["injected"].astype(bool)]
    return pd.DataFrame(
        {
            "trial_id": positives["trial_id"].to_numpy(),
            "quarter": positives["quarter"].to_numpy(),
            "rec_l7": positives["l7_recovered"].to_numpy(dtype=float),
            "rec_physics": positives["physics_recovered"].to_numpy(dtype=float),
        }
    )


def _comparison(
    stratum_frame: pd.DataFrame,
    report: dict,
    reasons: list[str],
    *,
    degenerate: list[str],
    resamples: int,
) -> dict:
    if reasons:
        return {
            "status": "inconclusive",
            "reasons": reasons,
            "estimate": None,
            "clusters": report["clusters"],
            "practical_superiority_claim": False,
        }
    result = v2.paired_comparison(
        _paired_frame(stratum_frame),
        fpr={
            "l7": float(report["fpr"]["l7"]["fpr"]),
            "physics": float(report["fpr"]["physics"]["fpr"]),
        },
        degenerate_strata=degenerate,
        resamples=resamples,
    )
    return {**result, "stratum": stratum_frame["noise_condition"].iloc[0]}


# --- evaluation --------------------------------------------------------------


def _authorized_campaign(
    effective: Mapping,
    manifest_dir: Path,
    real_authorization: authz.AuthorizationRef | None,
) -> dict | None:
    """Verify the OD-2 document for a real artifact; synthetic artifacts need none."""
    if real_authorization is None:
        return None
    fit_quarters, test_quarters = b7g.split_quarters(manifest_dir, effective)
    document, digest = authz.load_authorization_document(
        real_authorization,
        protocol_sha256=v2.AUTHORIZED_PROTOCOL_SHA256,
        manifest_hashes=v2.validate_manifests(Path(manifest_dir), dict(effective)),
        fit_quarters=fit_quarters,
        test_quarters=test_quarters,
        required_scope="campaign",
    )
    return {
        "document": document,
        "digest": digest,
        "binding": authz.authorization_binding(document, digest),
        "expected": b7g.expected_denominators(manifest_dir, effective),
    }


def _preclaim_generation_check(
    campaign: Path, real_authorization: authz.AuthorizationRef | None
) -> None:
    """Validate the generation marker before the one-shot access claim is consumed."""
    state = test_access.marker_state(campaign, test_access.MARKER_GENERATION)
    if state != "completed":
        raise GateError(f"generation marker is in state {state!r}; the artifact is not evaluable")
    record = json.loads(
        (Path(campaign) / test_access.MARKER_GENERATION).read_text(encoding="utf-8")
    )
    if record.get("source") == b7g.SOURCE and real_authorization is None:
        raise GateError(
            "the artifact carries real campaign trials; an authorization document is required"
        )
    if real_authorization is not None:
        b7g.require_generation_marker(campaign, real_authorization)


def _gated_inputs(effective, out_dir, manifest_dir, repo_root, mode):
    b1.assert_approved_mode(mode)
    b1.assert_approved_protocol(effective, v2.AUTHORIZED_PROTOCOL_SHA256)
    campaign = b2.resolve_campaign_dir(out_dir, manifest_dir=manifest_dir, repo_root=repo_root)
    phase11.assert_test_generation_allowed(campaign)
    fitted = v2.load_fitted_v21(campaign, v2.AUTHORIZED_PROTOCOL_SHA256)
    detector_thresholds = require_detector_table(fitted)
    l7_thresholds = require_score_table(fitted)
    degenerate = sorted(
        stratum
        for stratum, entry in fitted["thresholds"].items()
        if entry.get("threshold_degenerate")
    )
    return campaign, fitted, l7_thresholds, detector_thresholds, degenerate


def _evaluate(
    *,
    effective: Mapping,
    out_dir: Path,
    manifest_dir: Path,
    repo_root: Path,
    mode: object,
    resamples: int,
    real_authorization: authz.AuthorizationRef | None = None,
) -> dict:
    campaign, fitted, l7_thresholds, detector_thresholds, degenerate = _gated_inputs(
        effective, out_dir, manifest_dir, repo_root, mode
    )
    real = _authorized_campaign(effective, manifest_dir, real_authorization)
    # Marker, campaign and document bindings are validated *before* the claim, so a mismatched
    # marker cannot burn the single legitimate evaluation attempt.
    _preclaim_generation_check(campaign, real_authorization)

    # The one-shot claim is taken before the artifact is read: a second evaluation, an
    # interrupted run or a concurrent process is refused instead of re-reading the trials.
    test_access.claim_access(
        campaign,
        {
            "evaluator": EVALUATOR_NAME,
            "stage": "B3",
            "mode": MODE_SYNTHETIC,
            "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256,
            "fitted_sha256": fitted["_sha256"],
        },
    )

    frame = load_authorized_trials(campaign)
    checked = assert_test_trials(frame, fitted, real_authorization=real_authorization)
    generation = runner.verify_generated_trials(campaign)
    denominators = None
    if checked["kind"] == "real":
        b7g.require_generation_marker(campaign, real_authorization)
        observed = b7g.jsonable_observed(b7g.assert_denominators(frame, real["expected"]))
        denominators = {"expected": real["expected"], "observed": observed}
    scored = _score_frame(
        frame,
        fitted,
        campaign=campaign,
        l7_thresholds=l7_thresholds,
        detector_thresholds=detector_thresholds,
    )

    reports: dict[str, dict] = {}
    comparisons: dict[str, dict] = {}
    for stratum in checked["strata"]:
        stratum_frame = scored[scored["noise_condition"].astype(str) == stratum].copy()
        reasons = _insufficiency(stratum_frame)
        report = _stratum_report(stratum_frame)
        stratum_degenerate = [name for name in degenerate if name == stratum]
        reports[stratum] = {**report, "not_evaluated": reasons}
        comparisons[stratum] = _comparison(
            stratum_frame, report, reasons, degenerate=stratum_degenerate, resamples=resamples
        )

    combined = v2.combine_confirmatory(comparisons)
    metrics = {
        "phase": "11b",
        "stage": "B3",
        "schema_version": 1,
        "evaluator": EVALUATOR_NAME,
        "mode": MODE_SYNTHETIC,
        "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256,
        "fitted_sha256": fitted["_sha256"],
        "trials_sha256": generation["trials_sha256"],
        "model_id": fitted["model_id"],
        "timing_tolerance_days": float(TIMING_TOLERANCE_DAYS),
        "timing_tolerance_source": "protocol detection.timing_qualified_recovery",
        "operating_points": {"l7": l7_thresholds, "detector": detector_thresholds},
        "trials_rows": checked["rows"],
        "clusters": int(scored["quarter"].nunique()),
        "resamples": int(resamples),
        "per_stratum": reports,
        "comparison": combined,
        "practical_superiority_claim": False,
        "authorization": None if real is None else real["binding"],
        "denominators": denominators,
        "denominator_policy": (
            "protocol insufficient_data minima enforced; the frozen campaign literals "
            "(76 nulls, 72 injections per depth per stratum) are a real-campaign requirement"
        ),
        "limitations": [
            "false-positive intervals are trial-level and anti-conservative under within-quarter "
            "dependence; they are never described as cluster-adjusted",
            "five or fewer clusters; the resample count is not a count of independent units",
            "0.05 is the calibration target; the achieved test rate is reported with its "
            "interval and is never described as achieving 5 percent",
        ],
    }
    metrics_sha = v2.write_json_with_sidecar(campaign / METRICS_FILENAME, metrics)
    ledger = test_access.complete_marker(
        campaign,
        test_access.MARKER_ACCESS,
        {
            "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "test_rows": checked["rows"],
            "clusters": int(scored["quarter"].nunique()),
            "metrics_sha256": metrics_sha,
            "overall_status": combined["status"],
        },
    )
    return {
        "mode": MODE_SYNTHETIC,
        "campaign_dir": str(campaign),
        "metrics_path": str(campaign / METRICS_FILENAME),
        "metrics_sha256": metrics_sha,
        "trials_sha256": generation["trials_sha256"],
        "trials_rows": checked["rows"],
        "per_stratum": reports,
        "comparison": combined,
        "ledger": ledger,
    }


def _recorded_fitted_hash(campaign: Path) -> str | None:
    """Best-effort read of the frozen fitted digest for the refusal record; never raises."""
    try:
        sidecar = Path(campaign) / "fitted.sha256"
        if not sidecar.is_file():
            return None
        token = sidecar.read_text(encoding="utf-8").split()
    except OSError:
        return None
    if token and len(token[0]) == 64:
        return token[0]
    return None


def evaluate_test(
    *,
    effective: Mapping,
    out_dir: Path,
    audit_dir: Path,
    manifest_dir: Path,
    repo_root: Path,
    mode: object = MODE_SYNTHETIC,
    resamples: int = v2.BOOTSTRAP_RESAMPLES,
    real_authorization: authz.AuthorizationRef | None = None,
) -> dict:
    """Evaluate the generated test artifact once; every refusal leaves an audit record."""
    try:
        return _evaluate(
            effective=effective,
            out_dir=out_dir,
            manifest_dir=manifest_dir,
            repo_root=repo_root,
            mode=mode,
            resamples=resamples,
            real_authorization=real_authorization,
        )
    except (GateError, IntegrityError, OutputIsolationError) as exc:
        try:
            record_refusal(
                audit_dir,
                manifest_dir=manifest_dir,
                repo_root=repo_root,
                gate=type(exc).__name__,
                message=str(exc),
                effective=effective,
                campaign=Path(out_dir),
                fitted_sha256=_recorded_fitted_hash(Path(out_dir)),
            )
        except Exception as audit_exc:  # noqa: BLE001 - surfaced, never swallowed
            raise GateError(
                f"evaluation refused ({exc}); the G12 refusal audit could not be written "
                f"({audit_exc})"
            ) from exc
        raise
