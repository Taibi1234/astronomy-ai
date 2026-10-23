"""Real test generator tests: literal denominators, authorization binding, marker integrity.

Synthetic fixtures only. The fit frame and the generated test frame are synthetic; the frozen
manifests supply quarter identities, window slots, offsets and denominators. No real quarter is
read, no model is fitted on scientific data and no test artifact is evaluated.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import (  # noqa: E402, I001
    generalization as gen,
    phase11,
    phase11_authz as authz,
    phase11_b2a as b2a,
    phase11_b3 as b3,
    phase11_b7 as b7,
    phase11_b7_generate as b7g,
    phase11_runner as runner,
    phase11_v2 as v2,
    test_access,
)

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"
REPO_ROOT = gen.project_root()
FROZEN_NAMES = (
    "protocol_v2_3.json",
    "protocol_v2_3.sha256",
    "protocol.json",
    "protocol.sha256",
    "experiment_config.json",
)
CAMPAIGN_ID = "synthetic-campaign-b7"
COLUMNS = (
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
    "std_ppm",
    "mad_ppm",
    "mean_flux",
    "min_depth_ppm",
    "gap_fraction",
    "n_points",
)


@pytest.fixture(scope="module")
def effective() -> dict:
    missing = [name for name in FROZEN_NAMES if not (MANIFEST_DIR / name).is_file()]
    if missing:
        pytest.skip(f"frozen triple unavailable: {missing}")
    resolved, _ = v2.resolve_effective_protocol(MANIFEST_DIR)
    return resolved


@pytest.fixture(scope="module")
def quarters(effective) -> tuple[set[str], set[str]]:
    return b7g.split_quarters(MANIFEST_DIR, effective)


def _write_doc(
    tmp_path: Path,
    fit: set[str],
    test: set[str],
    campaign_id: str = CAMPAIGN_ID,
    name: str = "authorization.json",
) -> authz.AuthorizationRef:
    protocol, _digest = v2.load_protocol_v21(MANIFEST_DIR / v2.AUTHORIZED_PROTOCOL_NAME)
    doc = {
        "campaign_id": campaign_id,
        "approver": "test-owner",
        "operator": "test-operator",
        "issued_at": "2026-10-22T00:00:00Z",
        "scope": "fit_and_evaluate",
        "authorized_quarters": sorted(fit),
        "authorized_test_quarters": sorted(test),
        "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256,
        "manifest_hashes": v2.validate_manifests(MANIFEST_DIR, protocol),
        "single_run_ack": True,
    }
    path = tmp_path / name
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return authz.AuthorizationRef(path=path, sha256=v2.sha256_file(path), campaign_id=campaign_id)


@pytest.fixture
def authorization(tmp_path, quarters) -> authz.AuthorizationRef:
    fit, test = quarters
    return _write_doc(tmp_path, fit, test)


def _expected_frame(expected: dict) -> pd.DataFrame:
    """A cheap stand-in with exactly the expected counts (no detector calls)."""
    quarters = expected["test_quarters"]
    rows = []
    counter = 0

    def add(role: str, stratum: str, depth: float, injected: bool) -> None:
        nonlocal counter
        rows.append(
            {
                "trial_id": f"t{counter}",
                "quarter": quarters[counter % len(quarters)],
                "window_index": counter,
                "split": "test",
                "role": role,
                "requested_depth_ppm": depth,
                "injected": injected,
                "noise_condition": stratum,
                "source": b7g.SOURCE,
                "campaign_id": CAMPAIGN_ID,
                "delta_true_days": 0.0,
                "delta_est_days": 0.0,
                "snr": 1.0,
                "depth_est_ppm": 0.0,
                "sigma_ppm": 1.0,
                "std_ppm": 100.0,
                "mad_ppm": 80.0,
                "mean_flux": 1.0,
                "min_depth_ppm": 0.0,
                "gap_fraction": 0.0,
                "n_points": 200,
            }
        )
        counter += 1

    for stratum in expected["noise_conditions"]:
        for _index in range(expected["nulls_per_stratum"]):
            add("null_window", stratum, 0.0, False)
    for stratum in expected["noise_conditions"]:
        for depth in expected["depths_ppm"]:
            for _index in range(expected["injections_per_depth_per_stratum"]):
                add("injection", stratum, float(depth), True)
    return pd.DataFrame(rows, columns=list(COLUMNS))


@pytest.fixture(scope="module")
def fitted_campaign(tmp_path_factory, effective, quarters) -> Path:
    """Campaign directory holding a fitted state built from synthetic fit rows."""
    base = tmp_path_factory.mktemp("b7g")
    fit, test = quarters
    ref = _write_doc(base, fit, test)
    provenance = {
        "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256,
        "git": {"commit": "0" * 40, "branch": "main", "dirty": False, "dirty_paths": []},
    }
    frame = b2a.build_fit_split_frame(
        effective=effective,
        split_map={"Q00": "train", "Q04": "val"},
        seed=20261022,
        windows_per_quarter=34,
        depths_ppm=(300.0,),
    ).assign(source=b7.REAL_FIT_SOURCE, delta_true_days=0.0, delta_est_days=0.0)

    original_frame = b7.build_fit_frame
    original_capture = v2.capture_provenance
    b7.build_fit_frame = lambda **kwargs: frame
    v2.capture_provenance = lambda *args, **kwargs: provenance
    try:
        b7.fit_real(
            effective=effective,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            out_dir=base / "campaign",
            authorization=ref,
            model_id="L7_detector_plus_clean_flux",
        )
    finally:
        b7.build_fit_frame = original_frame
        v2.capture_provenance = original_capture
    return base / "campaign"


@pytest.fixture
def campaign(fitted_campaign, tmp_path) -> Path:
    target = tmp_path / "campaign"
    shutil.copytree(fitted_campaign, target)
    return target


# --- denominators ------------------------------------------------------------


def test_recomputed_denominators_match_the_protocol_literals(effective):
    expected = b7g.expected_denominators(MANIFEST_DIR, effective)

    assert expected["test_clusters"] == 5
    assert expected["nulls_pooled"] == 152
    assert expected["nulls_per_stratum"] == 76
    assert expected["injections_total"] == 720
    assert expected["injections_per_stratum"] == 360
    assert expected["injections_per_depth_per_stratum"] == 72


def test_denominator_drift_is_refused(effective, quarters, monkeypatch):
    real = b7g.test_windows

    def short(manifest_dir, eff, test_quarters):
        return real(manifest_dir, eff, test_quarters)[:-1]

    monkeypatch.setattr(b7g, "test_windows", short)

    with pytest.raises(phase11.GateError, match="do not match the frozen protocol literals"):
        b7g.expected_denominators(MANIFEST_DIR, effective)


def test_short_artifact_is_refused_before_claim(effective, campaign, authorization, monkeypatch):
    expected = b7g.expected_denominators(MANIFEST_DIR, effective)
    monkeypatch.setattr(
        b7g, "_build_test_rows", lambda **kwargs: _expected_frame(expected).head(10)
    )

    with pytest.raises(phase11.GateError, match="frozen denominators"):
        b7g.generate_real_test_trials(
            effective=effective,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            out_dir=campaign,
            authorization=authorization,
        )
    assert test_access.marker_state(campaign, test_access.MARKER_GENERATION) is None


# --- generation --------------------------------------------------------------


def test_generation_writes_the_authorized_artifact(effective, campaign, authorization, monkeypatch):
    frame = _expected_frame(b7g.expected_denominators(MANIFEST_DIR, effective))
    monkeypatch.setattr(b7g, "_build_test_rows", lambda **kwargs: frame)

    result = b7g.generate_real_test_trials(
        effective=effective,
        manifest_dir=MANIFEST_DIR,
        repo_root=REPO_ROOT,
        out_dir=campaign,
        authorization=authorization,
    )

    assert result["campaign_id"] == CAMPAIGN_ID
    assert result["trials_rows"] == len(frame)
    assert result["observed_denominators"]["nulls_pooled"] == 152
    assert result["observed_denominators"]["injections_per_depth_per_stratum"] == 72
    record = json.loads((campaign / test_access.MARKER_GENERATION).read_text(encoding="utf-8"))
    assert record["status"] == "completed"
    assert record["campaign_id"] == CAMPAIGN_ID
    assert record["authorization_sha256"] == authorization.sha256
    assert record["source"] == b7g.SOURCE
    info = runner.verify_generated_trials(campaign)
    assert info["trials_rows"] == len(frame)
    reloaded = runner.load_authorized_trials(campaign)
    assert set(reloaded["source"].unique()) == {b7g.SOURCE}


def test_duplicate_generation_is_refused(effective, campaign, authorization, monkeypatch):
    frame = _expected_frame(b7g.expected_denominators(MANIFEST_DIR, effective))
    monkeypatch.setattr(b7g, "_build_test_rows", lambda **kwargs: frame)
    b7g.generate_real_test_trials(
        effective=effective,
        manifest_dir=MANIFEST_DIR,
        repo_root=REPO_ROOT,
        out_dir=campaign,
        authorization=authorization,
    )

    with pytest.raises(phase11.GateError, match="markers are one-way"):
        b7g.generate_real_test_trials(
            effective=effective,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            out_dir=campaign,
            authorization=authorization,
        )


def test_generation_requires_a_hashed_document(effective, campaign, tmp_path):
    with pytest.raises(phase11.GateError, match="AuthorizationRef"):
        b7g.generate_real_test_trials(
            effective=effective,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            out_dir=campaign,
            authorization={"campaign_id": CAMPAIGN_ID},
        )
    missing = authz.AuthorizationRef(
        path=tmp_path / "absent.json", sha256="a" * 64, campaign_id=CAMPAIGN_ID
    )
    with pytest.raises(phase11.GateError, match="missing"):
        b7g.generate_real_test_trials(
            effective=effective,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            out_dir=campaign,
            authorization=missing,
        )


def test_generation_requires_a_frozen_fitted_state(effective, tmp_path, authorization):
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(phase11.GateError, match="before fitted.sha256"):
        b7g.generate_real_test_trials(
            effective=effective,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            out_dir=empty,
            authorization=authorization,
        )


def test_marker_binding_refuses_another_campaign(campaign, authorization):
    other = authz.AuthorizationRef(
        path=authorization.path, sha256=authorization.sha256, campaign_id="other"
    )

    with pytest.raises(phase11.GateError, match="state|not evaluable|does not name"):
        b7g.require_generation_marker(campaign, other)


# --- H2: marker validated before the access claim ----------------------------


def test_mismatched_marker_does_not_consume_the_access_claim(
    effective, campaign, authorization, tmp_path, monkeypatch
):
    frame = _expected_frame(b7g.expected_denominators(MANIFEST_DIR, effective))
    monkeypatch.setattr(b7g, "_build_test_rows", lambda **kwargs: frame)
    b7g.generate_real_test_trials(
        effective=effective,
        manifest_dir=MANIFEST_DIR,
        repo_root=REPO_ROOT,
        out_dir=campaign,
        authorization=authorization,
    )
    fit_quarters, test_quarters = b7g.split_quarters(MANIFEST_DIR, effective)
    other_doc = _write_doc(
        tmp_path,
        fit_quarters,
        test_quarters,
        campaign_id="other-campaign",
        name="other.json",
    )
    audit = tmp_path / "refusals"

    with pytest.raises(phase11.GateError, match="does not name the authorized campaign"):
        b3.evaluate_test(
            effective=effective,
            out_dir=campaign,
            audit_dir=audit,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            resamples=100,
            real_authorization=other_doc,
        )
    assert test_access.marker_state(campaign, test_access.MARKER_ACCESS) is None
    assert len(list(audit.glob("*.json"))) == 1

    result = b3.evaluate_test(
        effective=effective,
        out_dir=campaign,
        audit_dir=audit,
        manifest_dir=MANIFEST_DIR,
        repo_root=REPO_ROOT,
        resamples=100,
        real_authorization=authorization,
    )
    assert result["metrics_sha256"]
    assert test_access.marker_state(campaign, test_access.MARKER_ACCESS) == "completed"


# --- M1: exact per-cell denominators -----------------------------------------


def _mutate(frame: pd.DataFrame, mask, **updates) -> pd.DataFrame:
    out = frame.copy()
    for column, value in updates.items():
        out.loc[mask, column] = value
    return out


def test_imbalanced_null_strata_are_refused(effective):
    expected = b7g.expected_denominators(MANIFEST_DIR, effective)
    frame = _expected_frame(expected)
    first_observed_null = (frame["role"] == "null_window") & (
        frame["noise_condition"] == "observed"
    )
    index = frame.index[first_observed_null][0]
    imbalanced = _mutate(frame, frame.index == index, noise_condition="amplified_x2")

    assert len(imbalanced) == len(frame)
    with pytest.raises(phase11.GateError, match="nulls_by_stratum"):
        b7g.assert_denominators(imbalanced, expected)


def test_imbalanced_depth_cells_are_refused(effective):
    expected = b7g.expected_denominators(MANIFEST_DIR, effective)
    frame = _expected_frame(expected)
    cell = (
        (frame["role"] == "injection")
        & (frame["noise_condition"] == "observed")
        & (frame["requested_depth_ppm"] == 50.0)
    )
    index = frame.index[cell][0]
    imbalanced = _mutate(frame, frame.index == index, requested_depth_ppm=300.0)

    assert len(imbalanced) == len(frame)
    with pytest.raises(phase11.GateError, match="injections_by_cell"):
        b7g.assert_denominators(imbalanced, expected)


def test_unknown_cell_is_refused(effective):
    expected = b7g.expected_denominators(MANIFEST_DIR, effective)
    frame = _expected_frame(expected)
    cell = (frame["role"] == "injection") & (frame["requested_depth_ppm"] == 50.0)
    index = frame.index[cell][0]
    extra = _mutate(frame, frame.index == index, requested_depth_ppm=999.0)

    with pytest.raises(phase11.GateError, match="injections_by_cell"):
        b7g.assert_denominators(extra, expected)


# --- evaluator binding -------------------------------------------------------


def test_real_artifact_requires_authorization(effective):
    fitted = {"thresholds": {"observed": {"threshold": 0.5}}}
    frame = pd.DataFrame(
        [
            {
                "trial_id": "t1",
                "quarter": "Q02",
                "split": "test",
                "role": "null_window",
                "injected": False,
                "noise_condition": "observed",
                "campaign_id": CAMPAIGN_ID,
                "source": b7g.SOURCE,
                "delta_true_days": 0.0,
                "delta_est_days": 0.0,
                "snr": 1.0,
                "requested_depth_ppm": 0.0,
            }
        ]
    )

    with pytest.raises(phase11.GateError, match="authorization document is required"):
        b3.assert_test_trials(frame, fitted)
    with pytest.raises(phase11.GateError, match="campaign ids"):
        b3.assert_test_trials(
            frame,
            fitted,
            real_authorization=authz.AuthorizationRef(
                path=Path("x"), sha256="a" * 64, campaign_id="other"
            ),
        )


def test_denominator_check_refuses_a_short_real_artifact(effective):
    expected = b7g.expected_denominators(MANIFEST_DIR, effective)

    with pytest.raises(phase11.GateError, match="frozen denominators"):
        b7g.assert_denominators(_expected_frame(expected).head(10), expected)
