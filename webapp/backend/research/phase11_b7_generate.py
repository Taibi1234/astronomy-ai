"""Phase 11 B7: real test-trial generator with literal denominator enforcement (design D1/D3).

The generator writes ``trials_test.csv`` from the real test quarters, under the hashed OD-2
authorization document, the frozen fitted state and the shared one-shot generation claim. Before
anything is generated it recomputes the campaign denominators from the frozen inputs and refuses
unless they equal the protocol literals; after generation it refuses unless the observed counts
equal the recomputation. The B3 evaluator repeats the observed-count check before scoring.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd
import transit_injection as ti

from . import core, phase11, test_access
from . import phase11_authz as authz
from . import phase11_b1 as b1
from . import phase11_b2 as b2
from . import phase11_b7 as b7
from . import phase11_v2 as v2
from .features import time_domain_features
from .phase11 import GateError

TRIALS_FILENAME = "trials_test.csv"
SOURCE = authz.TEST_SOURCE
GENERATOR_NAME = "phase11-v2-b7-generator"
WINDOW_MANIFEST = "windows_primary.json"
WINDOW_DAYS = 5.0
MISSION = "kepler"
REQUIRED_COLUMNS = (
    "trial_id",
    "quarter",
    "window_index",
    "split",
    "role",
    "requested_depth_ppm",
    "injected",
    "noise_condition",
    "source",
    "campaign_id",
    "delta_true_days",
    "delta_est_days",
    "snr",
    "depth_est_ppm",
    "sigma_ppm",
)


def _manifests(manifest_dir: Path, effective: Mapping) -> dict[str, str]:
    return v2.validate_manifests(Path(manifest_dir), dict(effective))


def _read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def split_quarters(manifest_dir: Path, effective: Mapping) -> tuple[set[str], set[str]]:
    """Fit and test quarters from the frozen split manifest (fit reused for the fit gate)."""
    return b7.protocol_fit_quarters(manifest_dir, effective)


def test_windows(manifest_dir: Path, effective: Mapping, test_quarters: set[str]) -> list[dict]:
    """The frozen test windows only; a fit or foreign window is refused."""
    payload = _read_json(Path(manifest_dir) / WINDOW_MANIFEST)
    windows = payload.get("windows")
    if not isinstance(windows, list) or not windows:
        raise GateError("the frozen window manifest has no windows")
    if float(payload.get("window_days")) != WINDOW_DAYS:
        raise GateError("the generator produces the primary 5-day campaign only")
    kept = []
    for window in windows:
        quarter = str(window.get("quarter"))
        split = window.get("split")
        if split != "test":
            if quarter in test_quarters:
                raise GateError(f"window {quarter} is a test quarter but declares split {split!r}")
            continue
        if quarter not in test_quarters:
            raise GateError(f"window {quarter} declares test but is not a frozen test quarter")
        if window.get("role") not in ("null", "injection"):
            raise GateError(
                f"test window {quarter}/{window.get('window_index')} has a foreign role"
            )
        start, end = window.get("start_index"), window.get("end_index")
        if not isinstance(start, int) or not isinstance(end, int) or start >= end:
            raise GateError(f"test window {quarter}/{window.get('window_index')} has a bad slice")
        kept.append(window)
    if not kept:
        raise GateError("the frozen window manifest holds no test windows")
    return kept


def expected_denominators(manifest_dir: Path, effective: Mapping) -> dict:
    """Recompute the campaign denominators from the frozen inputs and check the literals."""
    _manifests(manifest_dir, effective)
    _fit, test_quarters = split_quarters(manifest_dir, effective)
    windows = test_windows(manifest_dir, effective, test_quarters)
    null_slots = sum(1 for window in windows if window["role"] == "null")
    injection_slots = sum(1 for window in windows if window["role"] == "injection")
    offsets, _hash = v2.load_frozen_offsets(Path(manifest_dir), dict(effective))
    draws = int(offsets["by_window_length"][f"{WINDOW_DAYS:.1f}"]["draws_per_window"])
    config = _read_json(Path(manifest_dir) / "experiment_config.json")
    depths = [float(depth) for depth in config["injection"]["depths_ppm"]]
    noise = [str(name) for name in config["injection"]["noise_conditions"]]
    if not depths or not noise or draws < 1:
        raise GateError("the frozen experiment config has no usable injection design")
    nulls = null_slots * draws * len(noise)
    injections = injection_slots * len(depths) * draws * len(noise)
    expected = {
        "test_clusters": len(test_quarters),
        "test_quarters": sorted(test_quarters),
        "null_slots": null_slots,
        "injection_slots": injection_slots,
        "offset_draws": draws,
        "nulls_pooled": nulls,
        "nulls_per_stratum": nulls // len(noise),
        "injections_total": injections,
        "injections_per_stratum": injections // len(noise),
        "injections_per_depth_per_stratum": injections // (len(noise) * len(depths)),
        "depths_ppm": depths,
        "noise_conditions": noise,
    }
    protocol = v2.load_protocol_v21(Path(manifest_dir) / v2.AUTHORIZED_PROTOCOL_NAME)[0]
    reporting = protocol["reporting"]["primary_denominators"]
    mismatches = []
    if expected["nulls_per_stratum"] != reporting["fpr_nulls"]:
        mismatches.append(
            f"nulls_per_stratum {expected['nulls_per_stratum']} != {reporting['fpr_nulls']}"
        )
    if expected["injections_per_stratum"] != reporting["detection_injections"]:
        mismatches.append(
            f"injections_per_stratum {expected['injections_per_stratum']} "
            f"!= {reporting['detection_injections']}"
        )
    if expected["injections_per_depth_per_stratum"] != reporting["injections_per_depth"]:
        mismatches.append(
            f"injections_per_depth_per_stratum {expected['injections_per_depth_per_stratum']} "
            f"!= {reporting['injections_per_depth']}"
        )
    if mismatches:
        raise GateError(
            "recomputed denominators do not match the frozen protocol literals: "
            + "; ".join(mismatches)
        )
    return expected


def observed_denominators(frame: pd.DataFrame) -> dict:
    """Observed counts of one generated artifact, cell by cell (not aggregates)."""
    nulls = frame[~frame["injected"].astype(bool)]
    positives = frame[frame["injected"].astype(bool)]
    nulls_by_stratum = {
        str(stratum): int(count)
        for stratum, count in nulls["noise_condition"].astype(str).value_counts().items()
    }
    injections_by_cell = {
        (str(stratum), float(depth)): int(count)
        for (stratum, depth), count in positives.groupby(["noise_condition", "requested_depth_ppm"])
        .size()
        .items()
    }
    return {
        "test_clusters": int(frame["quarter"].nunique()),
        "nulls_pooled": int(len(nulls)),
        "injections_total": int(len(positives)),
        "nulls_by_stratum": nulls_by_stratum,
        "injections_by_cell": injections_by_cell,
        "nulls_per_stratum": min(nulls_by_stratum.values()) if nulls_by_stratum else 0,
        "injections_per_stratum": (
            min(
                sum(
                    count
                    for (stratum_name, _depth), count in injections_by_cell.items()
                    if stratum_name == stratum
                )
                for stratum in {name for name, _depth in injections_by_cell}
            )
            if injections_by_cell
            else 0
        ),
        "injections_per_depth_per_stratum": (
            min(injections_by_cell.values()) if injections_by_cell else 0
        ),
    }


def _expected_cells(expected: Mapping) -> tuple[dict, dict]:
    nulls = {str(name): int(expected["nulls_per_stratum"]) for name in expected["noise_conditions"]}
    injections = {
        (str(name), float(depth)): int(expected["injections_per_depth_per_stratum"])
        for name in expected["noise_conditions"]
        for depth in expected["depths_ppm"]
    }
    return nulls, injections


def assert_denominators(frame: pd.DataFrame, expected: Mapping) -> dict:
    """Refuse any deviation from the recomputed campaign denominators, cell by cell."""
    observed = observed_denominators(frame)
    expected_nulls, expected_injections = _expected_cells(expected)
    problems: dict = {}
    if observed["test_clusters"] != int(expected["test_clusters"]):
        problems["test_clusters"] = (observed["test_clusters"], expected["test_clusters"])
    if observed["nulls_by_stratum"] != expected_nulls:
        problems["nulls_by_stratum"] = (observed["nulls_by_stratum"], expected_nulls)
    if observed["injections_by_cell"] != expected_injections:
        problems["injections_by_cell"] = (
            observed["injections_by_cell"],
            expected_injections,
        )
    if observed["nulls_pooled"] != int(expected["nulls_pooled"]):
        problems["nulls_pooled"] = (observed["nulls_pooled"], expected["nulls_pooled"])
    if observed["injections_total"] != int(expected["injections_total"]):
        problems["injections_total"] = (observed["injections_total"], expected["injections_total"])
    if problems:
        raise GateError(
            "generated artifact does not meet the frozen denominators "
            f"(observed, expected): {problems}"
        )
    return observed


def jsonable_observed(observed: Mapping) -> dict:
    """JSON-safe rendering of the observed counts (cell keys become ``stratum|depth``)."""
    rendered = dict(observed)
    rendered["injections_by_cell"] = {
        f"{stratum}|{float(depth):g}": int(count)
        for (stratum, depth), count in observed["injections_by_cell"].items()
    }
    return rendered


def _offset_lookup(offsets: Mapping) -> dict[tuple[str, int], list[float]]:
    table = offsets["by_window_length"][f"{WINDOW_DAYS:.1f}"]
    return {
        (str(row["quarter"]), int(row["window_index"])): list(row["offsets_days"])
        for row in table["draws"]
    }


def _build_test_rows(
    *,
    effective: Mapping,
    manifest_dir: Path,
    root: Path,
    campaign_id: str,
    test_quarters: set[str],
) -> pd.DataFrame:
    """Real test rows from the frozen test windows. The B3 evaluator repeats the count check."""
    windows = test_windows(manifest_dir, effective, test_quarters)
    plan = phase11.plan_trials(windows, dict(effective), "test")
    if set(plan["split"].unique()) != {"test"}:
        raise GateError("the real test plan contains non-test rows")
    offsets, _hash = v2.load_frozen_offsets(Path(manifest_dir), dict(effective))
    lookup = _offset_lookup(offsets)
    integrity = b7.quarter_integrity(manifest_dir, effective, test_quarters)
    by_key = {(str(window["quarter"]), int(window["window_index"])): window for window in windows}
    cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    rows = []
    for record in plan.to_dict(orient="records"):
        quarter = str(record["quarter"])
        window = by_key[(quarter, int(record["window_index"]))]
        if quarter not in cache:
            cache[quarter] = b7.load_verified_quarter(
                quarter, root, test_quarters, integrity=integrity, label="test"
            )
        times_all, flux_all = cache[quarter]
        times = np.asarray(times_all[window["start_index"] : window["end_index"]], dtype=float)
        flux = np.asarray(flux_all[window["start_index"] : window["end_index"]], dtype=float)
        cleaned, _amplitude = core.remove_published_transit(times, flux, MISSION)
        base = core.apply_noise_condition(cleaned, record["noise_condition"])
        delta = float(lookup[(quarter, int(record["window_index"]))][record["offset_index"]])
        if float(record["requested_depth_ppm"]) > 0:
            phase = core.phase_offsets(times, MISSION, delta)
            presented = ti.inject_transit(base, phase, float(record["requested_depth_ppm"]))
        else:
            presented = base.copy()
        detection = core.detect(times, presented, MISSION)
        rows.append(
            {
                **record,
                "source": SOURCE,
                "campaign_id": campaign_id,
                "delta_true_days": delta,
                "delta_est_days": float(detection["delta"]),
                "snr": float(detection["snr"]),
                "depth_est_ppm": float(detection["depth_ppm"]),
                "sigma_ppm": float(detection["sigma_ppm"]),
                **time_domain_features(times, presented),
            }
        )
    frame = pd.DataFrame(rows)
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise GateError(f"generated test frame is missing columns {missing}")
    return frame


def assert_generated_frame(frame: pd.DataFrame, test_quarters: set[str], campaign_id: str) -> None:
    if frame.empty:
        raise GateError("the generator produced no test rows")
    if set(frame["split"].unique()) != {"test"}:
        raise GateError("the generated artifact contains non-test rows")
    leaks = sorted({str(q) for q in frame["quarter"].unique()} - test_quarters)
    if leaks:
        raise GateError(f"the generated artifact touches non-test quarters {leaks}")
    sources = sorted({str(value) for value in frame["source"].unique()})
    if sources != [SOURCE]:
        raise GateError(f"the generated artifact must carry the {SOURCE!r} tag, got {sources}")
    campaigns = sorted({str(value) for value in frame["campaign_id"].unique()})
    if campaigns != [campaign_id]:
        raise GateError(
            f"the generated artifact campaign ids {campaigns} do not match {campaign_id}"
        )
    if bool(frame["trial_id"].duplicated().any()):
        raise GateError("the generated artifact has duplicate trial ids")


def generate_real_test_trials(
    *,
    effective: Mapping,
    manifest_dir: Path,
    repo_root: Path,
    out_dir: Path,
    authorization: authz.AuthorizationRef,
) -> dict:
    """Generate the authorized real test artifact; no evaluation and no scoring happens here."""
    b1.assert_approved_protocol(effective, v2.AUTHORIZED_PROTOCOL_SHA256)
    fit_quarters, test_quarters = split_quarters(manifest_dir, effective)
    document, digest = authz.load_authorization_document(
        authorization,
        protocol_sha256=v2.AUTHORIZED_PROTOCOL_SHA256,
        manifest_hashes=_manifests(manifest_dir, effective),
        fit_quarters=fit_quarters,
        test_quarters=test_quarters,
        required_scope="campaign",
    )
    campaign = b2.resolve_campaign_dir(out_dir, manifest_dir=manifest_dir, repo_root=repo_root)
    phase11.assert_test_generation_allowed(campaign)
    fitted = v2.load_fitted_v21(campaign, v2.AUTHORIZED_PROTOCOL_SHA256)
    test_access.assert_no_markers(campaign)

    expected = expected_denominators(manifest_dir, effective)
    frame = _build_test_rows(
        effective=effective,
        manifest_dir=manifest_dir,
        root=Path(repo_root),
        campaign_id=authorization.campaign_id,
        test_quarters=test_quarters,
    )
    assert_generated_frame(frame, test_quarters, authorization.campaign_id)
    observed = jsonable_observed(assert_denominators(frame, expected))

    campaign.mkdir(parents=True, exist_ok=True)
    b2.resolve_campaign_dir(campaign, manifest_dir=manifest_dir, repo_root=repo_root)
    test_access.assert_no_markers(campaign)
    test_access.claim_generation(
        campaign,
        {
            "generator": GENERATOR_NAME,
            "stage": "B7",
            "source": SOURCE,
            "campaign_id": authorization.campaign_id,
            "authorization_sha256": digest,
            "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256,
            "model_id": fitted.get("model_id"),
            "window_days": WINDOW_DAYS,
            "expected_denominators": expected,
            "observed_denominators": observed,
        },
    )
    target = campaign / TRIALS_FILENAME
    frame.to_csv(target, index=False)
    test_access.complete_marker(
        campaign,
        test_access.MARKER_GENERATION,
        {"trials_rows": int(len(frame)), "trials_sha256": v2.sha256_file(target)},
    )
    return {
        "generator": GENERATOR_NAME,
        "source": SOURCE,
        "campaign_id": authorization.campaign_id,
        "authorization_sha256": digest,
        "campaign_dir": str(campaign),
        "trials_path": str(target),
        "trials_sha256": v2.sha256_file(target),
        "trials_rows": int(len(frame)),
        "expected_denominators": expected,
        "observed_denominators": observed,
    }


def require_generation_marker(campaign: Path, authorization: authz.AuthorizationRef) -> dict:
    """Read and bind the generation marker for an authorized evaluation."""
    state = test_access.marker_state(campaign, test_access.MARKER_GENERATION)
    if state != "completed":
        raise GateError(f"generation marker is in state {state!r}; the artifact is not evaluable")
    record = json.loads(
        (Path(campaign) / test_access.MARKER_GENERATION).read_text(encoding="utf-8")
    )
    if record.get("campaign_id") != authorization.campaign_id:
        raise GateError("the generation marker does not name the authorized campaign")
    if record.get("authorization_sha256") != authorization.sha256:
        raise GateError("the generation marker was produced under a different authorization")
    if record.get("source") != SOURCE:
        raise GateError("the generation marker does not name the real test generator")
    return record
