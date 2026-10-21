"""Phase 8 — feature table with a recorded split and training-only imputation.

Phase 5 computed the `matched_filter_corr` imputation median over all 26 windows
(`scripts/phase5_features.py:33`), which lets a test-set value influence a
test-set feature. Phase 8 fits that statistic on TRAIN rows only and reuses it
unchanged for validation and test.

Writes `<out>/phase8_features.csv` and `<out>/phase8_feature_config.json`.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from phase8_split import SPLIT_SEED, assign_splits  # noqa: E402

FEATURE_NAMES = [
    "depth_rel_ppm",
    "contrast_ppm",
    "mad_scatter",
    "gap_fraction",
    "matched_filter_corr",
    "segment_std_ppm",
    "mean_flux",
]


def build(dataset_path, out_dir):
    payload = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    windows = payload["windows"]
    df = pd.DataFrame(
        [
            {
                **{k: w[k] for k in FEATURE_NAMES},
                "label": w["label"],
                "segment_id": w["segment_id"],
                "injected_depth_ppm": w["injected_depth_ppm"],
                "n_points": w["n_points"],
            }
            for w in windows
        ]
    )

    split, groups = assign_splits(df["segment_id"].values)
    df["split"] = split

    undefined = int(df["matched_filter_corr"].isna().sum())
    train_median = float(df.loc[df["split"] == "train", "matched_filter_corr"].median())
    df["matched_filter_corr"] = df["matched_filter_corr"].fillna(train_median)

    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "phase8_features.csv", index=False)

    config = {
        "features": {
            "depth_rel_ppm": "median - min of the presented window flux, times 1e6",
            "contrast_ppm": "mean(|phase|>3h) - mean(|phase|<=1.8h) of presented flux, times 1e6",
            "mad_scatter": "median absolute deviation of the presented flux",
            "gap_fraction": "fraction of cadences whose gap exceeds 0.05 d",
            "matched_filter_corr": "Pearson correlation with a fixed 150 ppm batman template",
            "segment_std_ppm": "standard deviation of the presented flux, times 1e6",
            "mean_flux": "mean of the presented flux",
        },
        "feature_source": (
            "presented window flux (transit injected when label=1); no label or depth argument"
        ),
        "label_source": "simulated injection only (positive=depth>0, negative=depth=0)",
        "no_real_planet_labels": True,
        "split_method": "segment-level; unique segments shuffled with RandomState(42), 50/25/25",
        "split_seed": SPLIT_SEED,
        "split_groups": {k: len(v) for k, v in groups.items()},
        "imputation": {
            "column": "matched_filter_corr",
            "rule": "median fitted on TRAIN rows only, applied unchanged to val/test",
            "value": train_median,
            "undefined_input_values": undefined,
        },
        "n_windows": int(len(df)),
    }
    (out_dir / "phase8_feature_config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Phase 8 features: {len(df)} rows | split={df['split'].value_counts().to_dict()}")
    print(f"Imputation median (train only): {train_median:.6f} over {undefined} undefined inputs")
    print(f"Output: {out_dir / 'phase8_features.csv'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "reports" / "phase8_dataset.json"))
    parser.add_argument("--out", default=str(ROOT / "reports"))
    args = parser.parse_args()
    build(args.dataset, Path(args.out))
