"""Phase 8 — guards for the corrected synthetic pipeline.

Checks the six properties the Phase 8 audit depends on:
1. features come from the flux actually presented to the classifier;
2. the extractor cannot see labels or injected depth;
3. positive and negative windows share one processing path;
4. parent segments never cross splits;
5. imputation statistics are fitted on training rows only;
6. the build is reproducible under a fixed seed.
"""

import ast
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from phase8_build_dataset import (  # noqa: E402
    POSITIVE_DEPTHS_PPM,
    build,
    extract_features,
    inject_transit,
)
from phase8_split import assign_splits  # noqa: E402

REPORTS = ROOT / "reports"
BUILDER = ROOT / "scripts" / "phase8_build_dataset.py"
PHASE5_DATASET = REPORTS / "phase5_dataset.json"
PHASE8_DATASET = REPORTS / "phase8_dataset.json"
PHASE8_FEATURES = REPORTS / "phase8_features.csv"
PHASE8_CONFIG = REPORTS / "phase8_feature_config.json"
INPUT_CSV = ROOT / "data" / "processed" / "kepler_all_quarters_quality_masked.csv"


def _window(n=24, depth_ppm=300.0):
    phase = np.linspace(-0.125, 0.125, n)
    flux = 1.0 + 1e-5 * np.arange(n)
    return flux, phase, np.sort(np.linspace(0.0, 0.5, n))


# --- 1. features are extracted from the intended (presented) input flux --------


def test_features_use_the_presented_flux():
    flux, phase, time = _window()
    injected = inject_transit(flux, phase, 300.0)

    pre = extract_features(flux, phase, time)
    post = extract_features(injected, phase, time)

    expected = float((np.median(injected) - np.min(injected)) * 1e6)
    assert post["depth_rel_ppm"] == pytest.approx(expected, rel=0, abs=1e-9)
    assert post["depth_rel_ppm"] > pre["depth_rel_ppm"], "a deeper dip must raise the depth feature"
    assert post["segment_std_ppm"] != pre["segment_std_ppm"]


def test_deeper_injection_produces_larger_depth_feature():
    flux, phase, time = _window()
    shallow = extract_features(inject_transit(flux, phase, POSITIVE_DEPTHS_PPM[0]), phase, time)
    deep = extract_features(inject_transit(flux, phase, POSITIVE_DEPTHS_PPM[-1]), phase, time)
    assert deep["depth_rel_ppm"] > shallow["depth_rel_ppm"]


def test_phase8_dataset_matches_the_frozen_phase5_dataset():
    """The frozen artifact is the presented-flux output; this pins that equivalence."""
    if not PHASE8_DATASET.is_file():
        pytest.skip("run scripts/phase8_build_dataset.py first")
    old = json.loads(PHASE5_DATASET.read_text(encoding="utf-8"))["windows"]
    new = json.loads(PHASE8_DATASET.read_text(encoding="utf-8"))["windows"]
    assert len(old) == len(new) == 26
    for a, b in zip(old, new, strict=True):
        for key in a:
            if isinstance(a[key], float) and a[key] != a[key]:
                assert b[key] != b[key], f"NaN mismatch in {key}"
            else:
                assert a[key] == b[key], f"field {key} differs for segment {a['segment_id']}"


# --- 2. the extractor cannot see labels or injected depth ----------------------


def test_extractor_signature_and_body_exclude_labels():
    tree = ast.parse(BUILDER.read_text(encoding="utf-8"))
    fn = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "extract_features"
    )

    arg_names = [a.arg for a in fn.args.args]
    assert arg_names == ["flux", "phase", "time"], arg_names

    referenced = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    forbidden = {"label", "injected_depth_ppm", "is_positive", "depth_ppm", "segment_id", "split"}
    assert not (referenced & forbidden), f"extractor references {referenced & forbidden}"


# --- 3. positives and negatives follow the same processing path ---------------


def test_single_extraction_site_for_both_classes():
    tree = ast.parse(BUILDER.read_text(encoding="utf-8"))
    build_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build")

    calls = [
        n
        for n in ast.walk(build_fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "extract_features"
    ]
    assert len(calls) == 1, "both classes must go through one extraction call"

    presented = {
        n.id for n in ast.walk(build_fn) if isinstance(n, ast.Name) and n.id == "presented_flux"
    }
    assert presented, "build() should name the presented flux explicitly"


# --- 4. parent segments never cross splits ------------------------------------


def test_parent_groups_do_not_cross_splits():
    df = pd.read_csv(PHASE8_FEATURES)
    sets = {
        name: set(df.loc[df["split"] == name, "segment_id"].tolist())
        for name in ("train", "val", "test")
    }
    assert sets["train"] and sets["val"] and sets["test"]
    assert not (sets["train"] & sets["val"])
    assert not (sets["train"] & sets["test"])
    assert not (sets["val"] & sets["test"])
    assert sets["train"] | sets["val"] | sets["test"] == set(df["segment_id"].tolist())
    # the rule must be the historical one
    expected, groups = assign_splits(df["segment_id"].values)
    assert list(expected) == df["split"].tolist()
    assert {k: len(v) for k, v in groups.items()} == {"train": 13, "val": 6, "test": 7}


# --- 5. imputation statistics come from training rows only --------------------


def test_imputation_median_is_fitted_on_train_rows_only():
    config = json.loads(PHASE8_CONFIG.read_text(encoding="utf-8"))
    windows = json.loads(PHASE8_DATASET.read_text(encoding="utf-8"))["windows"]

    seg = np.array([w["segment_id"] for w in windows])
    corr = np.array([w["matched_filter_corr"] for w in windows], dtype=float)
    split, _ = assign_splits(seg)

    train_values = corr[(split == "train") & ~np.isnan(corr)]
    all_values = corr[~np.isnan(corr)]
    assert config["imputation"]["value"] == pytest.approx(float(np.median(train_values)), abs=1e-12)
    assert float(np.median(train_values)) != pytest.approx(
        float(np.median(all_values)), abs=1e-12
    ), "train-only and all-window medians coincide; the test would not detect the fix"
    assert int(config["imputation"]["undefined_input_values"]) == int(np.isnan(corr).sum())


# --- 6. deterministic rebuild -------------------------------------------------


@pytest.mark.skipif(
    not INPUT_CSV.is_file(), reason="analysis-ready CSV is gitignored and not present"
)
def test_rebuild_is_deterministic(tmp_path):
    first = build(tmp_path / "a")
    second = build(tmp_path / "b")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert (tmp_path / "a" / "phase8_dataset.json").read_bytes() == (
        tmp_path / "b" / "phase8_dataset.json"
    ).read_bytes()
