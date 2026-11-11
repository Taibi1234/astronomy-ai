"""Synthetic-only regression tests for the Phase 11 Stage 2 hardening.

Every test builds its own fixtures in ``tmp_path`` or passes in-memory arrays. No campaign
data, no seeded test trial, and no historical artifact is read or written, with one
deliberate exception: the read-only checks of the frozen protocol use
``reports/phase11_generalization/protocol_v2_3.json`` and skip when it is absent, so the
suite also runs in a clean checkout without private data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import generalization as gen  # noqa: E402
from research import phase11, test_access  # noqa: E402
from research import phase11_v2 as v2  # noqa: E402

PROTOCOL_PATH = (
    gen.project_root() / "reports" / "phase11_generalization" / v2.AUTHORIZED_PROTOCOL_NAME
)
needs_frozen_protocol = pytest.mark.skipif(
    not PROTOCOL_PATH.is_file(), reason="frozen protocol_v2_3.json is not present"
)


# --- helpers ----------------------------------------------------------------


def _threshold_protocol(**overrides) -> dict:
    protocol = {
        "injection": {"noise_conditions": ["observed", "amplified_x2"]},
        "thresholds": {"target_fpr": 0.05, "min_calibration_n_per_stratum": 30},
    }
    protocol.update(overrides)
    return protocol


def _null_frame(n_per_stratum: int, strata=("observed", "amplified_x2"), split="train"):
    rows = []
    for stratum in strata:
        for index in range(n_per_stratum):
            rows.append(
                {
                    "role": "null_window",
                    "split": split,
                    "noise_condition": stratum,
                    "snr": 1.0 + index * 0.1,
                }
            )
    return pd.DataFrame(rows)


# --- protocol loading -------------------------------------------------------


@needs_frozen_protocol
def test_loads_the_authorized_protocol():
    payload, digest = v2.load_protocol_v21(PROTOCOL_PATH)
    assert digest == v2.AUTHORIZED_PROTOCOL_SHA256
    assert payload["version"] == "phase11b-protocol-v2.3-proposal"
    assert payload["schema_version"] == 2


def test_protocol_hash_pin_rejects_any_other_digest(tmp_path):
    path = _synthetic_protocol(tmp_path)
    with pytest.raises(v2.GateError, match="not the authorized protocol"):
        v2.load_protocol_v21(path, expected_sha256="0" * 64)


def test_protocol_sidecar_mismatch_is_refused(tmp_path):
    path = _synthetic_protocol(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["target"] = "tampered"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(v2.GateError, match="does not match its recorded hash"):
        v2.load_protocol_v21(path, expected_sha256=v2.sha256_file(path))


def test_protocol_requires_schema_two_and_every_section(tmp_path):
    path = _synthetic_protocol(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 1
    _rewrite(path, payload)
    with pytest.raises(v2.GateError, match="schema_version"):
        v2.load_protocol_v21(path, expected_sha256=v2.sha256_file(path))

    payload["schema_version"] = 2
    payload.pop("fpr")
    _rewrite(path, payload)
    with pytest.raises(v2.GateError, match="missing required sections"):
        v2.load_protocol_v21(path, expected_sha256=v2.sha256_file(path))


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda p: p["thresholds"].__setitem__("target_fpr", 0.10), "target_fpr"),
        (
            lambda p: p["thresholds"].__setitem__("min_calibration_n_per_stratum", 50),
            "min_calibration_n_per_stratum",
        ),
        (
            lambda p: p["approval_decisions"]["D2_timing_tolerance_days"].__setitem__(
                "value", 0.04
            ),
            "timing tolerance",
        ),
        (lambda p: p["detection"].__setitem__("comparison_operator", ">="), "strict"),
        (
            lambda p: p["approval_decisions"]["D1_minimum_meaningful_difference"].__setitem__(
                "value", 0.05
            ),
            "meaningful difference",
        ),
        (lambda p: p["bootstrap"].__setitem__("method_primary", "bca"), "percentile"),
    ],
)
def test_protocol_invariants_are_enforced(tmp_path, mutation, message):
    path = _synthetic_protocol(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutation(payload)
    _rewrite(path, payload)
    with pytest.raises(v2.GateError, match=message):
        v2.load_protocol_v21(path, expected_sha256=v2.sha256_file(path))


# --- manifest validation ----------------------------------------------------


def test_manifests_validated_by_hash_phase_and_structure(tmp_path):
    manifest_dir, protocol = _synthetic_manifests(tmp_path)
    assert set(v2.validate_manifests(manifest_dir, protocol)) == set(v2.MANIFEST_NAMES)

    original = (manifest_dir / "split.json").read_bytes()
    payload = json.loads(original)
    payload["phase"] = "10"
    (manifest_dir / "split.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(v2.GateError, match="does not match the protocol"):
        v2.validate_manifests(manifest_dir, protocol)

    (manifest_dir / "split.json").write_bytes(original)
    payload = json.loads(original)
    payload.pop("quotas")
    (manifest_dir / "split.json").write_text(json.dumps(payload), encoding="utf-8")
    protocol["frozen_inputs"]["files"]["split.json"] = v2.sha256_file(manifest_dir / "split.json")
    with pytest.raises(v2.GateError, match="missing required keys"):
        v2.validate_manifests(manifest_dir, protocol)


def test_manifest_validation_rejects_bad_phase_and_window_length(tmp_path):
    manifest_dir, protocol = _synthetic_manifests(tmp_path)
    payload = json.loads((manifest_dir / "split.json").read_text(encoding="utf-8"))
    payload["phase"] = "10"
    (manifest_dir / "split.json").write_text(json.dumps(payload), encoding="utf-8")
    protocol["frozen_inputs"]["files"]["split.json"] = v2.sha256_file(manifest_dir / "split.json")
    with pytest.raises(v2.GateError, match="phase"):
        v2.validate_manifests(manifest_dir, protocol)

    manifest_dir, protocol = _synthetic_manifests(tmp_path / "second")
    payload = json.loads((manifest_dir / "windows_primary.json").read_text(encoding="utf-8"))
    payload["window_days"] = 3.0
    (manifest_dir / "windows_primary.json").write_text(json.dumps(payload), encoding="utf-8")
    protocol["frozen_inputs"]["files"]["windows_primary.json"] = v2.sha256_file(
        manifest_dir / "windows_primary.json"
    )
    with pytest.raises(v2.GateError, match="5.0-day"):
        v2.validate_manifests(manifest_dir, protocol)


# --- threshold algorithm ----------------------------------------------------


def test_uniform_scores_return_the_interpolated_quantile():
    result = v2.choose_threshold_v21(np.arange(1, 101), scope="unit")
    assert result["threshold"] == pytest.approx(95.05)
    assert result["threshold_source"] == "quantile"
    assert result["calibration_exceedance"] == pytest.approx(0.05)
    assert result["floor_binding"] is False


def test_floor_above_quantile_is_selected_and_labelled():
    result = v2.choose_threshold_v21(np.arange(1, 101), floor=99.0, scope="unit")
    assert result["threshold"] == pytest.approx(99.0)
    assert result["threshold_source"] == "floor"
    assert result["floor_binding"] is True


def test_floor_equal_to_quantile_is_not_binding():
    result = v2.choose_threshold_v21(np.arange(1, 101), floor=95.05, scope="unit")
    assert result["threshold"] == pytest.approx(95.05)
    assert result["floor_binding"] is False
    assert result["threshold_source"] == "quantile"


def test_tie_lift_when_the_quantile_leaves_too_many_above():
    """n=30: the interpolated p95 leaves 2/30 = 0.0667 above, so the rule lifts."""
    result = v2.choose_threshold_v21(np.arange(0, 30), scope="unit")
    assert result["threshold"] == pytest.approx(28.0)
    assert result["threshold_source"] == "tie_lift"
    assert result["calibration_exceedance"] == pytest.approx(1 / 30)
    assert result["threshold"] > result["t0"]


def test_perfectly_tied_scores_are_handled():
    result = v2.choose_threshold_v21(np.full(40, 0.5), scope="unit")
    assert result["threshold"] == pytest.approx(0.5)
    assert result["calibration_exceedance"] == 0.0
    assert result["distinct_scores"] == 1
    assert result["threshold_source"] == "quantile"


def test_saturation_at_the_score_ceiling_is_flagged():
    scores = np.concatenate([np.full(20, 0.90), np.full(20, 1.0)])
    result = v2.choose_threshold_v21(scores, scope="unit", score_supremum=1.0)
    assert result["threshold"] == pytest.approx(1.0)
    assert result["threshold_degenerate"] is True

    safe = v2.choose_threshold_v21(np.linspace(0.0, 0.9, 60), scope="unit", score_supremum=1.0)
    assert safe["threshold_degenerate"] is False


def test_minimum_sample_is_enforced():
    with pytest.raises(v2.GateError, match="below the minimum"):
        v2.choose_threshold_v21(np.arange(29), scope="unit")
    with pytest.raises(v2.GateError, match="below the minimum"):
        v2.choose_threshold_v21(np.arange(29), scope="unit", min_n=30)


def test_non_finite_scores_are_dropped_not_counted():
    scores = np.concatenate([np.arange(1, 31), [np.nan, np.inf, -np.inf]])
    result = v2.choose_threshold_v21(scores, scope="unit")
    assert result["n"] == 30


@pytest.mark.parametrize("seed", range(20))
def test_exceedance_never_exceeds_the_target(seed):
    rng = np.random.default_rng(seed)
    scores = rng.normal(size=45)
    result = v2.choose_threshold_v21(scores, scope="unit")
    assert result["calibration_exceedance"] <= 0.05
    assert result["threshold"] >= result["quantile_q"]
    assert v2.exceedance(scores, result["threshold"]) <= 0.05


# --- calibration gates ------------------------------------------------------


def test_calibration_requires_every_declared_stratum():
    frame = _null_frame(30, strata=("observed",))
    with pytest.raises(v2.GateError, match="missing noise strata"):
        v2.calibrate_thresholds_v21(
            frame,
            _threshold_protocol(),
            score_column="snr",
            splits={"train", "val"},
            role="null_window",
            floor=3.0,
            score_supremum=None,
            context="unit",
        )


def test_calibration_refuses_test_rows():
    frame = _null_frame(30, split="test")
    with pytest.raises(v2.GateError, match="never be used for calibration"):
        v2.calibrate_thresholds_v21(
            frame,
            _threshold_protocol(),
            score_column="snr",
            splits={"train", "val"},
            role="null_window",
            floor=3.0,
            score_supremum=None,
            context="unit",
        )


def test_calibration_fails_closed_when_a_stratum_is_below_the_minimum():
    frame = _null_frame(10)
    with pytest.raises(v2.GateError, match="below the minimum"):
        v2.calibrate_thresholds_v21(
            frame,
            _threshold_protocol(),
            score_column="snr",
            splits={"train", "val"},
            role="null_window",
            floor=3.0,
            score_supremum=None,
            context="unit",
        )


def test_degenerate_stratum_fails_the_operability_gate():
    frame = _null_frame(30)
    frame.loc[frame["noise_condition"] == "observed", "snr"] = np.linspace(0.1, 0.5, 30)
    frame.loc[frame["noise_condition"] == "amplified_x2", "snr"] = 1.0
    thresholds = v2.calibrate_thresholds_v21(
        frame,
        _threshold_protocol(),
        score_column="snr",
        splits={"train", "val"},
        role="null_window",
        floor=None,
        score_supremum=1.0,
        context="unit",
    )
    assert thresholds["observed"]["threshold_degenerate"] is False
    assert thresholds["amplified_x2"]["threshold_degenerate"] is True
    with pytest.raises(v2.GateError, match="degenerate thresholds"):
        v2.assert_strata_operative(thresholds)


def test_calibration_records_provenance_per_stratum():
    frame = _null_frame(40)
    thresholds = v2.calibrate_thresholds_v21(
        frame,
        _threshold_protocol(),
        score_column="snr",
        splits={"train", "val"},
        role="null_window",
        floor=3.0,
        score_supremum=None,
        context="unit",
    )
    table = v2.stratum_table(thresholds)
    assert set(table) == {"observed", "amplified_x2"}
    for entry in table.values():
        assert entry["n"] == 40
        assert entry["threshold_source"] in {"quantile", "floor", "tie_lift"}
        assert entry["calibration_exceedance"] <= 0.05


# --- markers ----------------------------------------------------------------


def test_marker_round_trip_is_one_way(tmp_path):
    v2.begin_marker(tmp_path, v2.MARKER_GENERATION, {"protocol_sha256": "abc"})
    assert v2.marker_state(tmp_path, v2.MARKER_GENERATION) == "started"
    record = v2.complete_marker(tmp_path, v2.MARKER_GENERATION, {"trials_sha256": "def"})
    assert record["status"] == "completed"
    assert record["trials_sha256"] == "def"
    assert v2.marker_state(tmp_path, v2.MARKER_GENERATION) == "completed"


def test_second_begin_is_refused_in_every_state(tmp_path):
    with pytest.raises(v2.GateError, match="does not exist"):
        v2.complete_marker(tmp_path, v2.MARKER_ACCESS)

    v2.begin_marker(tmp_path, v2.MARKER_ACCESS, {})
    with pytest.raises(v2.GateError, match="already exists"):
        v2.begin_marker(tmp_path, v2.MARKER_ACCESS, {})
    v2.complete_marker(tmp_path, v2.MARKER_ACCESS)
    with pytest.raises(v2.GateError, match="already exists"):
        v2.begin_marker(tmp_path, v2.MARKER_ACCESS, {})
    with pytest.raises(v2.GateError, match="only started"):
        v2.complete_marker(tmp_path, v2.MARKER_ACCESS)


def test_crashed_run_leaves_terminal_evidence(tmp_path):
    v2.begin_marker(tmp_path, v2.MARKER_GENERATION, {})
    # simulated crash: no completion, no cleanup
    with pytest.raises(v2.GateError, match="already exists"):
        v2.begin_marker(tmp_path, v2.MARKER_GENERATION, {})
    with pytest.raises(v2.GateError, match="never reset"):
        v2.assert_no_markers(tmp_path)


def test_unreadable_marker_is_not_treated_as_absent(tmp_path):
    (tmp_path / v2.MARKER_ACCESS).write_text("{not json", encoding="utf-8")
    assert v2.marker_state(tmp_path, v2.MARKER_ACCESS) == "invalid"
    with pytest.raises(v2.GateError, match="invalid"):
        v2.assert_no_markers(tmp_path)


def test_concurrent_creation_fails_closed(tmp_path, monkeypatch):
    def racing_open(path, payload):
        raise FileExistsError("simulated race")

    monkeypatch.setattr(test_access, "_write_exclusive", racing_open)
    with pytest.raises(v2.GateError, match="concurrently"):
        v2.begin_marker(tmp_path, v2.MARKER_GENERATION, {})


def test_module_has_no_marker_deletion_path():
    source = Path(v2.__file__).read_text(encoding="utf-8")
    for token in ("unlink", "os.remove", "shutil.rmtree", "reset_marker", "delete_marker"):
        assert token not in source, f"markers must never be removable by software: {token}"


# --- freeze and load --------------------------------------------------------


def _freeze_protocol() -> dict:
    return {
        "version": "phase11b-protocol-v2.3-proposal",
        "preprocessing": {"fit_splits": ["train"]},
    }


def test_freeze_refuses_after_either_marker_exists(tmp_path):
    for marker in v2.MARKERS:
        out_dir = tmp_path / marker.replace(".json", "")
        out_dir.mkdir()
        (out_dir / marker).write_text(
            json.dumps({"status": "started", "marker": marker}), encoding="utf-8"
        )
        with pytest.raises(v2.GateError, match="one-way"):
            v2.freeze_fitted_v21(
                out_dir,
                fitted=_fitted(),
                model=object(),
                trials=_fit_frame(),
                protocol=_freeze_protocol(),
                protocol_hash="abc",
                provenance={},
            )


def test_fitted_round_trip_and_tamper_detection(tmp_path):
    frozen = v2.freeze_fitted_v21(
        tmp_path,
        fitted=_fitted(),
        model={"weights": [1, 2, 3]},
        trials=_fit_frame(),
        protocol=_freeze_protocol(),
        protocol_hash="abc",
        provenance={"git": {"commit": "deadbeef", "dirty": False}},
    )
    assert set(frozen) == {"fitted.json", "model.pkl"}

    loaded = v2.load_fitted_v21(tmp_path, "abc")
    assert loaded["protocol_version"] == "phase11b-protocol-v2.3-proposal"
    assert loaded["thresholds"]["observed"]["threshold_source"] == "quantile"

    with pytest.raises(v2.GateError, match="different protocol"):
        v2.load_fitted_v21(tmp_path, "other")

    (tmp_path / "model.pkl").write_bytes(b"tampered")
    with pytest.raises(v2.GateError, match="model file does not match"):
        v2.load_fitted_v21(tmp_path, "abc")


def test_fitted_without_sidecar_or_provenance_is_refused(tmp_path):
    (tmp_path / "model.pkl").write_bytes(b"x")
    payload = {
        "schema_version": 2,
        "protocol_sha256": "abc",
        "model_file": "model.pkl",
        "model_sha256": phase11.sha256_file(tmp_path / "model.pkl"),
    }
    phase11.write_json_with_sidecar(tmp_path / "fitted.json", payload)
    with pytest.raises(v2.GateError, match="no provenance"):
        v2.load_fitted_v21(tmp_path, "abc")

    (tmp_path / "fitted.sha256").unlink()
    with pytest.raises(v2.GateError, match="fitted.sha256 is missing"):
        v2.load_fitted_v21(tmp_path, "abc")


# --- provenance -------------------------------------------------------------


def test_git_provenance_reports_dirtiness(tmp_path, monkeypatch):
    def fake_git(root, *args):
        if args[0] == "status":
            return " M research/phase11.py"
        return "abc123" if args[1] == "HEAD" else "main"

    monkeypatch.setattr(v2, "_git", fake_git)
    provenance = v2.git_provenance(tmp_path)
    assert provenance["dirty"] is True
    with pytest.raises(v2.GateError, match="clean tracked tree"):
        v2.require_clean_tree(provenance)


def test_clean_tree_passes(tmp_path, monkeypatch):
    def fake_git(root, *args):
        if args[0] == "status":
            return ""
        return "abc123" if args[1] == "HEAD" else "main"

    monkeypatch.setattr(v2, "_git", fake_git)
    provenance = v2.git_provenance(tmp_path)
    assert provenance["dirty"] is False
    v2.require_clean_tree(provenance)


def test_git_failure_fails_closed(tmp_path, monkeypatch):
    def boom(root, *args):
        raise v2.GateError("git rev-parse HEAD failed: not a repository")

    monkeypatch.setattr(v2, "_git", boom)
    with pytest.raises(v2.GateError, match="not a repository"):
        v2.git_provenance(tmp_path)


def test_source_manifest_hash_is_deterministic_and_content_bound(tmp_path):
    repo = tmp_path
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "b.py").write_text("y = 2\n", encoding="utf-8")
    first = v2.source_manifest_hash([repo / "b.py", repo / "a.py"], repo)
    second = v2.source_manifest_hash([repo / "a.py", repo / "b.py"], repo)
    assert first == second
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert v2.source_manifest_hash([repo / "a.py", repo / "b.py"], repo) != first


def test_source_manifest_rejects_paths_outside_the_repository(tmp_path):
    outside = tmp_path.parent / "outside.py"
    with pytest.raises(v2.GateError, match="outside the repository"):
        v2.source_manifest_hash([outside], tmp_path / "repo")


# --- comparison -------------------------------------------------------------


def _paired_frame(per_quarter: dict[str, tuple[float, float]]) -> pd.DataFrame:
    rows = []
    for quarter, (l7, physics) in per_quarter.items():
        for repeat in range(2):
            rows.append(
                {
                    "quarter": quarter,
                    "trial_id": f"{quarter}-{repeat}",
                    "rec_l7": l7,
                    "rec_physics": physics,
                }
            )
    return pd.DataFrame(rows)


def _steady_frame() -> pd.DataFrame:
    """Positive but non-identical differences, so the bootstrap is not degenerate."""
    frame = _paired_frame(
        {
            "Q00": (1.0, 0.0),
            "Q01": (1.0, 0.0),
            "Q02": (1.0, 0.0),
            "Q03": (0.9, 0.1),
            "Q04": (0.9, 0.1),
        }
    )
    return frame


def test_unset_mmd_forbids_practical_superiority():
    result = v2.paired_comparison(_steady_frame(), resamples=200)
    assert result["status"] == "descriptive_only"
    assert result["practical_superiority_claim"] is False
    assert result["interval"]["method"] == "percentile"
    assert result["interval"]["primary"] is True
    assert result["bca"]["diagnostic_only"] is True


def test_explicit_mmd_override_is_refused():
    with pytest.raises(v2.GateError, match="caller-supplied overrides are refused"):
        v2.paired_comparison(_steady_frame(), mmd=0.10, resamples=200)


def test_fpr_mismatch_makes_the_comparison_inconclusive():
    result = v2.paired_comparison(_steady_frame(), resamples=200, fpr={"l7": 0.06, "physics": 0.02})
    assert result["status"] == "inconclusive"
    assert any("mismatch" in reason for reason in result["reasons"])


def test_matched_operating_points_pass_the_gate():
    result = v2.paired_comparison(_steady_frame(), resamples=200, fpr={"l7": 0.04, "physics": 0.03})
    assert result["status"] == "descriptive_only"
    assert result["practical_superiority_claim"] is False


def test_heterogeneity_guard_fires_on_two_opposite_quarters():
    frame = _paired_frame(
        {
            "Q00": (1.0, 0.0),
            "Q01": (1.0, 0.0),
            "Q02": (1.0, 0.0),
            "Q03": (0.0, 1.0),
            "Q04": (0.0, 1.0),
        }
    )
    result = v2.paired_comparison(frame, resamples=200)
    assert result["status"] == "inconclusive"
    assert any("heterogeneity" in reason for reason in result["reasons"])


def test_degenerate_interval_is_inconclusive_not_equivalence():
    frame = _paired_frame({f"Q{index:02d}": (0.0, 0.0) for index in range(5)})
    result = v2.paired_comparison(frame, resamples=200)
    assert result["status"] == "inconclusive"
    assert any(
        "quarters contribute" in reason or "distinct" in reason for reason in result["reasons"]
    )
    assert "equivalent" not in json.dumps(result).lower()


def test_too_few_clusters_is_inconclusive():
    frame = _paired_frame({"Q00": (1.0, 0.0), "Q01": (1.0, 0.0)})
    result = v2.paired_comparison(frame, resamples=100)
    assert result["status"] == "inconclusive"
    assert any("clusters" in reason for reason in result["reasons"])


def test_duplicate_trial_ids_break_pairing():
    frame = _steady_frame()
    frame.loc[frame.index[0], "trial_id"] = frame["trial_id"].iloc[1]
    with pytest.raises(v2.GateError, match="duplicate trial ids"):
        v2.paired_comparison(frame, resamples=100)


def test_intersection_union_rule():
    superior = {"status": "superior"}
    inconclusive = {"status": "inconclusive"}
    not_superior = {"status": "not_superior"}
    descriptive = {"status": "descriptive_only"}

    assert (
        v2.combine_confirmatory({"observed": superior, "amplified_x2": superior})["status"]
        == "superior"
    )
    assert (
        v2.combine_confirmatory({"observed": superior, "amplified_x2": inconclusive})["status"]
        == "inconclusive"
    )
    assert (
        v2.combine_confirmatory({"observed": superior, "amplified_x2": not_superior})["status"]
        == "not_superior"
    )
    assert (
        v2.combine_confirmatory({"observed": superior, "amplified_x2": descriptive})["status"]
        == "descriptive_only"
    )


# --- false-positive rate ----------------------------------------------------


def test_zero_false_positive_bounds_match_the_protocol():
    assert v2.zero_fp_upper_bound(76) == pytest.approx(0.0387, abs=5e-4)
    assert v2.zero_fp_upper_bound(152) == pytest.approx(0.0195, abs=5e-4)
    assert v2.zero_fp_upper_bound(0) is None


def test_fpr_report_uses_the_one_sided_bound_only_at_zero():
    zero = v2.fpr_report(0, 76)
    assert zero["fpr"] == 0.0
    assert zero["primary_interval"]["method"].startswith("clopper-pearson")
    assert "cluster" not in zero
    assert "anti-conservative" in zero["wilson_label"]

    positive = v2.fpr_report(3, 76)
    assert positive["fpr"] == pytest.approx(3 / 76)
    assert "clopper-pearson" not in positive["primary_interval"]["method"]

    with pytest.raises(v2.GateError, match="positive denominator"):
        v2.fpr_report(0, 0)
    with pytest.raises(v2.GateError, match="cannot exceed"):
        v2.fpr_report(5, 3)


# --- campaign preconditions -------------------------------------------------


def test_preconditions_refuse_markers_and_manifest_directory(tmp_path, monkeypatch):
    manifest_dir, _protocol = _synthetic_manifests(tmp_path / "manifests")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    v2.begin_marker(out_dir, v2.MARKER_ACCESS, {})

    monkeypatch.setattr(v2, "load_protocol_v21", lambda path, **kwargs: ({}, "abc"))
    monkeypatch.setattr(v2, "validate_manifests", lambda d, p: {})
    monkeypatch.setattr(v2, "load_frozen_offsets", lambda d, p: ({}, "abc"))

    with pytest.raises(v2.GateError, match="one-way"):
        v2.campaign_preconditions(manifest_dir, out_dir, tmp_path, source_paths=[])

    clean_out = tmp_path / "clean"
    clean_out.mkdir()
    with pytest.raises(v2.GateError, match="must not be the manifest directory"):
        v2.campaign_preconditions(manifest_dir, manifest_dir, tmp_path, source_paths=[])


def test_preconditions_refuse_a_dirty_tree(tmp_path, monkeypatch):
    manifest_dir, _protocol = _synthetic_manifests(tmp_path / "manifests")
    out_dir = tmp_path / "out"
    monkeypatch.setattr(v2, "load_protocol_v21", lambda path, **kwargs: ({}, "abc"))
    monkeypatch.setattr(v2, "validate_manifests", lambda d, p: {})
    monkeypatch.setattr(v2, "load_frozen_offsets", lambda d, p: ({}, "abc"))
    monkeypatch.setattr(
        v2,
        "git_provenance",
        lambda root: {
            "commit": "abc",
            "branch": "main",
            "dirty": True,
            "dirty_paths": [" M research/phase11.py"],
        },
    )
    with pytest.raises(v2.GateError, match="clean tracked tree"):
        v2.campaign_preconditions(manifest_dir, out_dir, tmp_path, source_paths=[])


# --- fixtures ---------------------------------------------------------------


def _synthetic_protocol(tmp_path: Path) -> Path:
    payload = {
        "phase": "11b",
        "schema_version": 2,
        "version": "phase11b-protocol-v2.3-proposal",
        "status": "synthetic test fixture",
        "supersedes": {},
        "approval_decisions": {
            "D1_minimum_meaningful_difference": {"value": None},
            "D2_timing_tolerance_days": {"value": 0.0377},
        },
        "data_roles": {"l7_calibration": "all null_window trials with split == val"},
        "detection": {
            "comparison_operator": "strict >",
            "timing_qualified_recovery": (
                "recovered := detected AND abs(timing_error_days) <= 0.0377"
            ),
        },
        "thresholds": {"target_fpr": 0.05, "min_calibration_n_per_stratum": 30},
        "reporting": {"primary_family": "per noise_condition"},
        "fpr": {},
        "comparison": {},
        "bootstrap": {"method_primary": "percentile"},
        "insufficient_data": {},
        "test_access": {"markers": list(v2.MARKERS)},
        "provenance": {},
        "frozen_inputs": {"files": {}},
    }
    path = tmp_path / "protocol_v2_3.json"
    phase11.write_json_with_sidecar(path, payload)
    return path


def _rewrite(path: Path, payload: dict) -> Path:
    phase11.write_json_with_sidecar(path, payload)
    return path


def _synthetic_manifests(tmp_path: Path):
    manifest_dir = tmp_path / "phase11_generalization"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        "split.json": {
            "phase": "11a",
            "unit_of_independence": "kepler quarter",
            "quotas": {"train": 1, "val": 1, "test": 1},
            "seed": 1,
            "assignment": {"Q00": "train", "Q01": "val", "Q02": "test"},
            "quarters": [],
        },
        "windows_primary.json": {
            "phase": "11a",
            "window_days": 5.0,
            "rules": {},
            "windows": [
                {
                    "quarter": "Q00",
                    "split": "train",
                    "role": "null",
                    "window_index": 0,
                    "start_index": 0,
                    "end_index": 10,
                }
            ],
        },
        "windows_sensitivity.json": {
            "phase": "11a",
            "window_days": 3.0,
            "rules": {},
            "windows": [
                {
                    "quarter": "Q00",
                    "split": "train",
                    "role": "null",
                    "window_index": 0,
                    "start_index": 0,
                    "end_index": 10,
                }
            ],
        },
        "null_library.json": {"primary": {}, "sensitivity": {}},
        "experiment_config.json": {
            "phase": "11a",
            "target": "Kepler-10 b",
            "unit_of_independence": "kepler quarter",
            "split": {},
            "window": {},
            "injection": {"noise_conditions": ["observed", "amplified_x2"]},
            "ml_ladder": [],
            "metrics": {},
        },
    }
    hashes = {}
    for name, payload in payloads.items():
        phase11.write_json_with_sidecar(manifest_dir / name, payload)
        hashes[name] = v2.sha256_file(manifest_dir / name)
    protocol = {"frozen_inputs": {"files": hashes}}
    return manifest_dir, protocol


def _fit_frame() -> pd.DataFrame:
    return pd.DataFrame({"split": ["train", "val"], "trial_id": ["a", "b"], "injected": [1, 0]})


def _fitted() -> dict:
    return {
        "model_id": "L7_detector_plus_clean_flux",
        "features": ["snr"],
        "dropped_features": [],
        "imputation_medians": [0.0],
        "train_rows": 1,
        "val_rows": 1,
        "train_injected": 1,
        "thresholds": {
            "observed": {
                "threshold": 0.5,
                "threshold_source": "quantile",
                "n": 42,
                "calibration_exceedance": 0.02,
                "floor_binding": False,
                "threshold_degenerate": False,
                "distinct_scores": 30,
            }
        },
        "detector_thresholds": {
            "observed": {
                "threshold": 3.5,
                "floor": 3.0,
                "floor_applied": True,
                "n": 134,
                "calibration_exceedance": 0.04,
                "target_fpr": 0.05,
                "scope": "detector|observed|train+val nulls",
                "percentile_method": "linear",
                "comparison": ">",
            }
        },
    }
