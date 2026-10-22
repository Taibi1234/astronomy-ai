"""Phase 11a tests: frozen split, window rules, null library, leakage guards.

No campaign is run and no model is fitted here; every assertion is about the
pre-registered manifest being internally consistent and reproducible.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import generalization as gen  # noqa: E402

# The quarter CSVs are gitignored (data/processed/*), so these tests are local-only.
QUARTER_DIR = gen.project_root() / "data" / "processed"
_QUARTER_FILES = sorted(QUARTER_DIR.glob("kepler_q*_quality_masked.csv"))
pytestmark = pytest.mark.skipif(
    not _QUARTER_FILES,
    reason=(
        "requires local Kepler quarter CSVs in data/processed/ "
        "(gitignored; see reports/phase11_research_plan.md §2.8)"
    ),
)


@pytest.fixture(scope="module")
def manifests():
    return gen.build_manifests()


@pytest.fixture(scope="module")
def times_by_quarter():
    return {q: gen.load_quarter(p)[0] for q, p in gen.quarter_files().items()}


def _windows(manifests, label="primary"):
    key = "windows_primary.json" if label == "primary" else "windows_sensitivity.json"
    return manifests[key]["windows"]


# --- split integrity ---------------------------------------------------------


def test_split_covers_every_quarter_with_frozen_quotas(manifests):
    split = manifests["split.json"]
    assignment = split["assignment"]
    assert len(assignment) == 15
    assert set(assignment) == set(split["quarters"])
    counts = {s: sum(1 for v in assignment.values() if v == s) for s in ("train", "val", "test")}
    assert counts == {"train": 7, "val": 3, "test": 5}
    assert assignment == gen.SPLIT_ASSIGNMENT


def test_every_window_inherits_its_quarter_partition(manifests):
    for label in ("primary", "sensitivity"):
        for window in _windows(manifests, label):
            assert window["split"] == gen.SPLIT_ASSIGNMENT[window["quarter"]]


def test_every_split_holds_at_least_one_long_and_one_short_quarter(manifests):
    quarters = manifests["split.json"]["quarters"]
    for split in ("train", "val", "test"):
        spans = [q["span_days"] for q in quarters.values() if q["split"] == split]
        assert any(span >= gen.SHORT_QUARTER_DAYS for span in spans)
        assert any(span < gen.SHORT_QUARTER_DAYS for span in spans)


# --- window generation rules -------------------------------------------------


def test_no_window_spans_a_major_gap(manifests, times_by_quarter):
    for label in ("primary", "sensitivity"):
        for window in _windows(manifests, label):
            times = times_by_quarter[window["quarter"]]
            seg = times[window["start_index"] : window["end_index"]]
            assert np.all(np.diff(seg) <= gen.MAJOR_GAP_DAYS), window["quarter"]


def test_windows_within_a_quarter_do_not_overlap(manifests):
    for label in ("primary", "sensitivity"):
        by_quarter: dict[str, list[dict]] = {}
        for window in _windows(manifests, label):
            by_quarter.setdefault(window["quarter"], []).append(window)
        for quarter, windows in by_quarter.items():
            ordered = sorted(windows, key=lambda w: w["start_index"])
            for left, right in zip(ordered, ordered[1:], strict=False):
                assert left["end_index"] <= right["start_index"], quarter


def test_window_geometry_matches_pre_registered_rules(manifests, times_by_quarter):
    lengths = (
        ("primary", gen.WINDOW_DAYS["primary"]),
        ("sensitivity", gen.WINDOW_DAYS["sensitivity"]),
    )
    for label, window_days in lengths:
        for window in _windows(manifests, label):
            times = times_by_quarter[window["quarter"]]
            seg = times[window["start_index"] : window["end_index"]]
            assert window["n_points"] == len(seg) >= gen.MIN_WINDOW_POINTS
            assert window["time_start"] == pytest.approx(float(seg[0]))
            assert window["time_end"] == pytest.approx(float(seg[-1]))
            duration = float(seg[-1] - seg[0])
            assert duration >= gen.MIN_WINDOW_FRACTION * window_days
            assert duration / gen.PERIOD_DAYS >= gen.MIN_TRANSITS
            assert duration <= window_days + 1e-6


def test_window_generation_is_gap_aware_on_a_synthetic_curve():
    times = np.concatenate(
        [
            np.arange(0.0, 8.0, 29.4 / 1440.0),      # piece A, 8 d -> one 5 d window
            np.arange(12.0, 20.0, 29.4 / 1440.0),    # piece B after a 4 d gap -> one 5 d window
        ]
    )
    windows = gen.generate_windows(times, "Q02", 5.0)
    # 8-day pieces yield one full window each; the 3-day tails fail the 80% rule.
    assert len(windows) == 2
    assert windows[0].time_start < 8.0 < windows[1].time_start
    for window in windows:
        seg = times[window.start_index : window.end_index]
        assert np.all(np.diff(seg) <= gen.MAJOR_GAP_DAYS)
        assert seg[-1] - seg[0] <= 5.0 + 1e-6


def test_short_tail_is_dropped_but_a_long_enough_tail_is_kept():
    short_tail = np.arange(0.0, 4.9, 29.4 / 1440.0)   # 4.9 d: < 5 d, kept as a tail window
    assert len(gen.generate_windows(short_tail, "Q02", 5.0)) == 1
    three_days = np.arange(0.0, 3.9, 29.4 / 1440.0)  # 3.9 d: below 0.8 * 5 d -> dropped
    assert gen.generate_windows(three_days, "Q02", 5.0) == []


def test_roles_cover_every_window_and_stay_balanced_per_quarter(manifests):
    for label in ("primary", "sensitivity"):
        by_quarter: dict[str, list[dict]] = {}
        for window in _windows(manifests, label):
            by_quarter.setdefault(window["quarter"], []).append(window)
        for quarter, windows in by_quarter.items():
            ordered = sorted(windows, key=lambda w: w["window_index"])
            assert [w["window_index"] for w in ordered] == list(range(len(ordered)))
            assert {w["role"] for w in ordered} <= {"injection", "null"}
            injections = sum(w["role"] == "injection" for w in ordered)
            nulls = sum(w["role"] == "null" for w in ordered)
            assert injections + nulls == len(ordered), quarter
            assert abs(injections - nulls) <= 1, quarter


def test_role_assignment_is_deterministic(manifests):
    again = gen.build_manifests()
    for label in ("primary", "sensitivity"):
        first = [(w["quarter"], w["window_index"], w["role"]) for w in _windows(manifests, label)]
        second = [(w["quarter"], w["window_index"], w["role"]) for w in _windows(again, label)]
        assert first == second


def test_odd_tail_uses_its_own_coin():
    # Three separate 5-day pieces -> three windows -> one pair plus a tail.
    times = np.concatenate(
        [
            np.arange(0.0, 6.0, 29.4 / 1440.0),
            np.arange(10.0, 16.0, 29.4 / 1440.0),
            np.arange(20.0, 26.0, 29.4 / 1440.0),
        ]
    )
    windows = gen.generate_windows(times, "Q03", 5.0)
    assert len(windows) == 3
    roles = [w.role for w in windows]
    assert abs(roles.count("injection") - roles.count("null")) == 1
    expected_tail = "injection" if gen.role_coin("Q03", "tail", 5.0) else "null"
    assert roles[-1] == expected_tail
    # The pair is decided by its own coin, one injection and one null.
    assert {roles[0], roles[1]} == {"injection", "null"}


def test_roles_do_not_depend_on_flux_values(manifests, monkeypatch):
    baseline = {
        (w["quarter"], w["window_index"]): w["role"]
        for w in _windows(manifests, "primary")
    }
    original = gen.load_quarter

    def scaled_loader(path):
        times, flux, excluded = original(path)
        return times, flux * 3.0 + 0.5, excluded

    monkeypatch.setattr(gen, "load_quarter", scaled_loader)
    altered = gen.build_manifests()
    monkeypatch.undo()
    scaled = {
        (w["quarter"], w["window_index"]): w["role"]
        for w in _windows(altered, "primary")
    }
    assert scaled == baseline


def test_roles_do_not_depend_on_the_offset_seed(manifests, monkeypatch):
    baseline = {
        (w["quarter"], w["window_index"]): w["role"]
        for w in _windows(manifests, "primary")
    }
    monkeypatch.setattr(gen, "OFFSET_SEED", gen.OFFSET_SEED + 7)
    altered = gen.build_manifests()
    monkeypatch.undo()
    moved = {
        (w["quarter"], w["window_index"]): w["role"]
        for w in _windows(altered, "primary")
    }
    assert moved == baseline


def test_temporal_role_balance_is_not_systematic(manifests, times_by_quarter):
    from scipy import stats  # noqa: PLC0415 - only this test needs scipy

    for label in ("primary", "sensitivity"):
        by_quarter: dict[str, list[dict]] = {}
        for window in _windows(manifests, label):
            by_quarter.setdefault(window["quarter"], []).append(window)
        pooled: dict[str, list[float]] = {"injection": [], "null": []}
        per_quarter = []
        for quarter, windows in by_quarter.items():
            times = times_by_quarter[quarter]
            relative = {}
            for window in windows:
                seg_lo, seg_hi = gen.contiguous_pieces(times)[window["piece_index"]]
                piece = times[seg_lo:seg_hi]
                relative[window["window_index"]] = (
                    (window["time_start"] - piece[0]) / (piece[-1] - piece[0])
                )
                pooled[window["role"]].append(relative[window["window_index"]])
            inj = [relative[w["window_index"]] for w in windows if w["role"] == "injection"]
            nul = [relative[w["window_index"]] for w in windows if w["role"] == "null"]
            per_quarter.append(sum(inj) / len(inj) - sum(nul) / len(nul))

        a = np.array(pooled["injection"])
        b = np.array(pooled["null"])
        effect = (a.mean() - b.mean()) / np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
        assert abs(effect) < 0.25, f"{label}: |Cohen's d| too large ({effect:.2f})"
        earlier = sum(1 for diff in per_quarter if diff < 0)
        tied = sum(1 for diff in per_quarter if diff == 0)
        untied = len(per_quarter) - tied
        p_value = stats.binomtest(earlier, untied, 0.5).pvalue if untied else 1.0
        assert p_value > 0.10, f"{label}: systematic role/time association (p={p_value:.3f})"



def test_injection_and_null_windows_never_share_cadences(manifests):
    for label in ("primary", "sensitivity"):
        by_quarter: dict[str, list[dict]] = {}
        for window in _windows(manifests, label):
            by_quarter.setdefault(window["quarter"], []).append(window)
        for quarter, windows in by_quarter.items():
            injections = [w for w in windows if w["role"] == "injection"]
            nulls = [w for w in windows if w["role"] == "null"]
            for injection in injections:
                for null in nulls:
                    assert (
                        injection["end_index"] <= null["start_index"]
                        or null["end_index"] <= injection["start_index"]
                    ), quarter


# --- null library ------------------------------------------------------------


def test_null_library_calibration_never_touches_test_quarters(manifests):
    library = manifests["null_library.json"]
    test_quarters = {q for q, s in gen.SPLIT_ASSIGNMENT.items() if s == "test"}
    for label in library:
        calibration_quarters = set(library[label]["calibration"]["quarters"])
        test_null_quarters = set(library[label]["test"]["quarters"])
        assert calibration_quarters & test_quarters == set()
        assert test_null_quarters <= test_quarters
        assert calibration_quarters & test_null_quarters == set()


def test_null_library_counts_match_the_window_manifests(manifests):
    library = manifests["null_library.json"]
    lengths = (
        ("primary", "windows_primary.json"),
        ("sensitivity", "windows_sensitivity.json"),
    )
    for label, key in lengths:
        windows = manifests[key]["windows"]
        nulls = [w for w in windows if w["role"] == "null"]
        injections = [w for w in windows if w["role"] == "injection"]
        entry = library[label]
        assert entry["calibration"]["null_windows"] + entry["test"]["null_windows"] == len(nulls)
        assert entry["test"]["null_windows"] == sum(
            1 for w in nulls if w["split"] == "test"
        )
        assert entry["paired_controls"]["windows"] == len(injections)
        assert entry["target_fpr"] == pytest.approx(0.05)
        assert "threshold calibration" in entry["paired_controls"]["excluded_from"]


# --- leakage guards ----------------------------------------------------------


def test_every_feature_set_excludes_ground_truth_columns(manifests):
    config = manifests["experiment_config.json"]
    forbidden = set(config["forbidden_feature_columns"])
    for entry in config["ml_ladder"]:
        leaked = forbidden & set(entry["features"])
        assert leaked == set(), f"{entry['id']} leaks {leaked}"


def test_feature_sets_only_use_measured_quantities(manifests):
    config = manifests["experiment_config.json"]
    allowed = set(gen.DETECTOR_OUTPUTS) | set(gen.FLUX_FEATURES_FULL)
    for entry in config["ml_ladder"]:
        assert set(entry["features"]) <= allowed, entry["id"]
    assert {"delta_true_days", "requested_depth_ppm", "injected"} <= set(
        config["forbidden_feature_columns"]
    )


def test_min_depth_proxy_is_compared_with_and_without(manifests):
    config = manifests["experiment_config.json"]
    ladder = {entry["id"]: set(entry["features"]) for entry in config["ml_ladder"]}
    assert "min_depth_ppm" in ladder["L4_flux_full"]
    for model_id in ("L5_flux_without_depth_proxy", "L6_flux_clean", "L7_detector_plus_clean_flux"):
        assert "min_depth_ppm" not in ladder[model_id]
    # The contrast must be exact: L5 differs from L4 only by the proxy.
    assert ladder["L4_flux_full"] - ladder["L5_flux_without_depth_proxy"] == {"min_depth_ppm"}


def test_group_identifier_features_are_isolated_in_the_ladder(manifests):
    ladder = {e["id"]: set(e["features"]) for e in manifests["experiment_config.json"]["ml_ladder"]}
    assert {"n_points", "gap_fraction"} <= ladder["L4_flux_full"]
    assert not {"n_points", "gap_fraction"} & ladder["L6_flux_clean"]
    # L7 is the realistic model: detector outputs + flux features without proxies or group ids.
    assert {"snr", "depth_est_ppm", "sigma_ppm"} <= ladder["L7_detector_plus_clean_flux"]
    assert "min_depth_ppm" not in ladder["L7_detector_plus_clean_flux"]


def test_config_declares_five_percent_fpr_and_never_one_percent(manifests):
    config = manifests["experiment_config.json"]
    null_library = config["null_library"]
    assert null_library["target_fpr"] == pytest.approx(0.05)
    assert "0.01" not in json.dumps(null_library)
    assert "1%" not in json.dumps(null_library).replace("no 1% target", "")
    assert "no 1% target" in json.dumps(null_library)


# --- determinism and feasibility ---------------------------------------------


def test_manifests_are_byte_deterministic(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    gen.write_manifests(first)
    gen.write_manifests(second)
    for path in sorted(first.iterdir()):
        assert path.read_bytes() == (second / path.name).read_bytes(), path.name


def test_feasibility_passes_for_both_window_lengths(manifests):
    report = gen.feasibility_report(manifests)
    for label in ("primary", "sensitivity"):
        assert report[label]["pass"] is True, report[label]
        for split, row in report[label]["splits"].items():
            assert row["injection_windows"] >= gen.FEASIBILITY_MINIMUMS[
                "injection_windows"
            ][split]
            assert row["null_windows"] >= gen.FEASIBILITY_MINIMUMS["null_windows"][split]
            assert row["positives_per_depth"] >= gen.FEASIBILITY_MINIMUMS[
                "positives_per_depth_per_split"
            ]
            low, high = gen.FEASIBILITY_MINIMUMS["per_depth_balance_range"]
            assert low <= row["per_depth_balance"] <= high


def test_excluding_short_quarters_remains_feasible(manifests):
    quarters = manifests["split.json"]["quarters"]
    short = {q for q, entry in quarters.items() if entry["short"]}
    assert short == {"Q00", "Q01", "Q04", "Q17"}
    for label in ("primary", "sensitivity"):
        windows = _windows(manifests, label)
        kept = [w for w in windows if w["quarter"] not in short]
        for split in ("train", "val", "test"):
            subset = [w for w in kept if w["split"] == split]
            injections = [w for w in subset if w["role"] == "injection"]
            nulls = [w for w in subset if w["role"] == "null"]
            assert {w["quarter"] for w in subset}
            assert len(injections) >= gen.FEASIBILITY_MINIMUMS["injection_windows"][split]
            assert len(nulls) >= gen.FEASIBILITY_MINIMUMS["null_windows"][split]


def test_projected_cost_is_recorded_for_both_lengths(manifests):
    cost = manifests["experiment_config.json"]["projected_cost"]
    for label in ("primary", "sensitivity"):
        assert cost[label]["total_detector_trials"] > 0
        assert cost[label]["projected_seconds"] > 0
        assert cost[label]["model"].startswith("t = 0.019 s")
