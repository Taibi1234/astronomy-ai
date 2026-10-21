"""Phase 5 — leakage, label, and split invariants for the saved ML dataset.

Converted in Phase 7 from module-level assertions (which pytest reported as
"0 items") into discoverable test functions. Paths resolve from this file, so the
suite can be run from any working directory.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

REPORTS = Path(__file__).resolve().parents[1] / "reports"
FEATURES_FILE = REPORTS / "phase5_features.csv"
DATASET_FILE = REPORTS / "phase5_dataset.json"
CONFIG_FILE = REPORTS / "phase5_feature_config.json"
RESULTS_FILE = REPORTS / "phase5_results.json"

FEATURE_NAMES = [
    "depth_rel_ppm",
    "contrast_ppm",
    "mad_scatter",
    "gap_fraction",
    "matched_filter_corr",
    "segment_std_ppm",
    "mean_flux",
]


@pytest.fixture(scope="module")
def dataset():
    return json.loads(DATASET_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def windows(dataset):
    return dataset["windows"]


@pytest.fixture(scope="module")
def features():
    return pd.read_csv(FEATURES_FILE)


@pytest.fixture(scope="module")
def config():
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def test_saved_artifacts_exist():
    for path in (FEATURES_FILE, DATASET_FILE, CONFIG_FILE, RESULTS_FILE):
        assert path.is_file(), f"missing saved artifact: {path.name}"


def test_label_consistency_per_segment(windows):
    seen = {}
    for w in windows:
        sid = w["segment_id"]
        if sid in seen:
            assert seen[sid] == w["label"], f"segment {sid} has inconsistent labels"
        seen[sid] = w["label"]


def test_each_window_uses_a_distinct_parent_segment(windows):
    segment_ids = [w["segment_id"] for w in windows]
    assert len(segment_ids) == len(set(segment_ids)), (
        "a parent segment contributed more than one window; the segment-level split "
        "would then not guarantee train/test separation"
    )


def test_positive_labels_come_from_injection(windows):
    positives = [w for w in windows if w["label"] == 1]
    assert positives, "expected at least one positive window"
    assert all(w["injected_depth_ppm"] > 0 for w in positives)


def test_negative_labels_are_uninjected(windows):
    negatives = [w for w in windows if w["label"] == 0]
    assert negatives, "expected at least one negative window"
    assert all(w["injected_depth_ppm"] == 0 for w in negatives)


def test_classes_are_balanced(windows):
    n_pos = sum(w["label"] for w in windows)
    assert n_pos == len(windows) - n_pos, "dataset is not 50/50 positive/negative"


def test_feature_config_declares_synthetic_only_labels(config):
    assert config["no_real_planet_labels"] is True
    assert "simulated injection" in config["label_source"]
    assert config["split_method"]


def test_feature_config_lists_all_features(config):
    assert sorted(config["features"]) == sorted(FEATURE_NAMES)


def test_features_csv_has_no_missing_values(features):
    assert not features.isnull().values.any(), "NaN found in feature CSV"


def test_features_csv_schema(features):
    expected = FEATURE_NAMES + ["label", "segment_id", "injected_depth_ppm", "n_points"]
    assert list(features.columns) == expected


def test_features_csv_row_count_matches_dataset(features, windows):
    assert len(features) == len(windows) == 26


def test_features_csv_rows_align_with_dataset(features, windows):
    assert features["segment_id"].tolist() == [w["segment_id"] for w in windows]
    assert features["label"].tolist() == [w["label"] for w in windows]


def test_matched_filter_nan_is_median_imputed(features, windows):
    """Undefined correlations in the dataset JSON are replaced by the median in the CSV."""
    valid = [
        w["matched_filter_corr"]
        for w in windows
        if w["matched_filter_corr"] == w["matched_filter_corr"]
    ]
    undefined = [
        i for i, w in enumerate(windows) if w["matched_filter_corr"] != w["matched_filter_corr"]
    ]
    assert len(undefined) == 9, (
        "NaN-correlation count changed; update the documented imputation note"
    )
    median = (
        sorted(valid)[len(valid) // 2]
        if len(valid) % 2
        else (sorted(valid)[len(valid) // 2 - 1] + sorted(valid)[len(valid) // 2]) / 2
    )
    for row in undefined:
        assert features.loc[row, "matched_filter_corr"] == pytest.approx(median, abs=1e-12)


def test_split_sizes_are_consistent_with_dataset(windows):
    results = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    total = results["n_train"] + results["n_val"] + results["n_test"]
    assert total == len(windows), "split sizes do not cover the dataset exactly once"
    assert results["n_train"] > 0 and results["n_val"] > 0 and results["n_test"] > 0


def test_results_declare_no_discovery_claim():
    results = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    assert results["no_discovery_claim"] is True
    warning = results["synthetic_only_warning"].lower()
    assert "simulated windows only" in warning
    assert "unverified" in warning
    assert "synthetic injection only" in results["label_source_note"].lower()
