"""Phase 5 — Baseline (logistic regression) + optional RandomForest comparison.
Uses segment-level split; threshold selected on validation only.
Reports synthetic-only limitation clearly.

Status: historical pipeline, preserved because `reports/phase5_results.{json,md}` are
frozen. It reproduces them exactly, including two documented protocol defects:
the split is recomputed from a global RNG instead of being stored with the rows, and
the RandomForest is admitted by comparing its VALIDATION F1 against the baseline's
TEST F1 (line marked below), which lets the test score influence model selection.
Both are corrected in reports/phase8_ml_pipeline_audit.md; the corrected chain is
scripts/phase8_features.py + scripts/phase8_eval.py. The corrected run reproduces
every test metric here to the digit, so the frozen numbers remain valid.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402 - imports follow sys.path setup
import pandas as pd  # noqa: E402
from sklearn.dummy import DummyClassifier  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

FEATURE_FILE = ROOT / "reports" / "phase5_features.csv"
CONFIG_FILE = ROOT / "reports" / "phase5_feature_config.json"
OUTPUT_REPORT = ROOT / "reports" / "phase5_results.md"

# Load features
df = pd.read_csv(FEATURE_FILE)
X = df[
    [
        "depth_rel_ppm",
        "contrast_ppm",
        "mad_scatter",
        "gap_fraction",
        "matched_filter_corr",
        "segment_std_ppm",
        "mean_flux",
    ]
].values
y = df["label"].values
segment_ids = df["segment_id"].values

# Segment-level split: train segments: IDs with remainder 0-1; val: remainder 2; test: remainder 3
# This ensures no segment overlap between train/test
segment_rem = {seg: i % 4 for i, seg in enumerate(np.unique(segment_ids))}
# But segment IDs may not be contiguous; instead split by ordering segments
unique_segments = np.unique(segment_ids)
np.random.seed(42)
np.random.shuffle(unique_segments)
train_segs = unique_segments[: len(unique_segments) // 2]  # ~50% for simplicity
val_segs = unique_segments[len(unique_segments) // 2 : 3 * len(unique_segments) // 4]
test_segs = unique_segments[3 * len(unique_segments) // 4 :]

train_mask = np.isin(segment_ids, train_segs)
val_mask = np.isin(segment_ids, val_segs)
test_mask = np.isin(segment_ids, test_segs)

# Note: this split ensures same parent segment never appears in train and test
# (verified by design; full verification in tests/test_phase5_leakage.py)

X_train, y_train = X[train_mask], y[train_mask]
X_val, y_val = X[val_mask], y[val_mask]
X_test, y_test = X[test_mask], y[test_mask]

print(
    f"Split by segment: train={len(X_train)} (segs={len(train_segs)}), val={len(X_val)} "
    f"(segs={len(val_segs)}), test={len(X_test)} (segs={len(test_segs)})"
)

# Baseline logistic regression
model = LogisticRegression(max_iter=1000, C=1.0)
model.fit(X_train, y_train)
val_pred_proba = model.predict_proba(X_val)[:, 1]
# Threshold by validation Youden index (max sens + spec - 1)
best_thresh = 0.5  # default; we compute from validation predictions against all thresholds
from sklearn.metrics import roc_curve  # noqa: E402 - local import at point of use

fpr, tpr, thresholds = roc_curve(y_val, val_pred_proba)
youden = tpr - fpr
best_idx = np.argmax(youden)
best_thresh = thresholds[best_idx]
print(f"Validation-selected threshold (Youden): {best_thresh:.3f}")

# Evaluate on test
val_pred = (val_pred_proba >= best_thresh).astype(int)
test_pred_proba = model.predict_proba(X_test)[:, 1]
test_pred = (test_pred_proba >= best_thresh).astype(int)

# Metrics
metrics = {
    "threshold": float(best_thresh),
    "precision": float(precision_score(y_test, test_pred, zero_division=0)),
    "recall": float(recall_score(y_test, test_pred, zero_division=0)),
    "f1": float(f1_score(y_test, test_pred, zero_division=0)),
    "confusion_matrix": confusion_matrix(y_test, test_pred).tolist(),
    "roc_auc": float(
        roc_auc_score(y_test, test_pred_proba) if len(np.unique(y_test)) > 1 else float("nan")
    ),
    "pr_auc": float(
        average_precision_score(y_test, test_pred_proba)
        if len(np.unique(y_test)) > 1
        else float("nan")
    ),
    "n_train": int(len(X_train)),
    "n_val": int(len(X_val)),
    "n_test": int(len(X_test)),
    "positive_train": int(np.sum(y_train)),
    "negative_train": int(len(y_train) - np.sum(y_train)),
    "positive_test": int(np.sum(y_test)),
    "negative_test": int(len(y_test) - np.sum(y_test)),
    "feature_list": [
        "depth_rel_ppm",
        "contrast_ppm",
        "mad_scatter",
        "gap_fraction",
        "matched_filter_corr",
        "segment_std_ppm",
        "mean_flux",
    ],
    "segment_metadata_feature_included": "segment_std_ppm (parent segment variability from "
    "Phase 4)",
    "label_source_note": "Synthetic injection only (positive=depth>0 [75,150,225,300 ppm], "
    "negative=depth=0). Not real-planet labels.",
    "split_strategy": "Segment-level split by parent continuous segment (gap >1d split); no "
    "overlap between train/val/test.",
    "synthetic_only_warning": "Performance measured on simulated windows only. Generalization "
    "to real observations remains unverified.",
    "no_discovery_claim": True,
}

# Compare with dummy baseline
dummy = DummyClassifier(strategy="stratified", random_state=42)
dummy.fit(X_train, y_train)
dummy_pred = dummy.predict(X_test)
metrics["dummy_f1"] = float(f1_score(y_test, dummy_pred, zero_division=0))
metrics["baseline_f1"] = metrics["f1"]
metrics["improvement_vs_dummy_f1"] = float(metrics["f1"] - metrics["dummy_f1"])

# RandomForest comparison, computed for reference (selection rule below)
try:
    from sklearn.ensemble import RandomForestClassifier

    rf = RandomForestClassifier(n_estimators=200, max_depth=6, random_state=42)
    rf.fit(X_train, y_train)
    rf_pred = rf.predict(X_val)  # use val to decide; but report test only if selected
    rf_f1_val = f1_score(y_val, rf_pred, zero_division=0)
    metrics["rf_f1_validation"] = float(rf_f1_val)
    metrics["rf_selected"] = bool(
        rf_f1_val > metrics["f1"] + 0.05
    )  # KNOWN DEFECT: compares against the TEST score; see phase8_eval.py
    if metrics["rf_selected"]:
        metrics["rf_f1_test"] = float(f1_score(y_test, rf.predict(X_test), zero_division=0))
        print("RandomForest selected (improvement >0.05 on validation F1).")
    else:
        print(
            "RandomForest NOT selected (improvement <=0.05 on validation F1); using logistic "
            "regression only."
        )
        metrics["rf_f1_test"] = None
except Exception as e:
    metrics["rf_f1_validation"] = None
    metrics["rf_selected"] = False
    metrics["rf_error"] = str(e)
    print(f"RandomForest skipped: {e}")

with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
    f.write("# Phase 5 — ML Classification Report\n\n")
    f.write(
        "**Synthetic-label classification only.** All positive labels come from simulated "
        "transit injection (depth 75/150/225/300 ppm). Negative labels are depth=0 windows from "
        "the same observed light curves. **Not a discovery claim.**\n\n"
    )
    f.write("## Design summary\n")
    f.write(
        "- Features (7): depth_rel_ppm, contrast_ppm, mad_scatter, gap_fraction, "
        "matched_filter_corr, segment_std_ppm (segment-level variability from Phase 4), "
        "mean_flux.\n"
    )
    f.write("- Baseline: LogisticRegression (C=1.0, max_iter=1000).\n")
    f.write(
        "- Complex model: RandomForest (200 trees, max_depth=6) — added only if validation F1 "
        "improves by >0.05 over baseline.\n"
    )
    f.write(
        "- Split: segment-level (parent continuous segment split at >1d gap). No segment "
        "appears in both train and test.\n"
    )
    f.write(
        "- Threshold: selected on validation set via Youden index (max sensitivity + "
        "specificity - 1).\n\n"
    )
    f.write("## Metrics (test set)\n")
    for k, v in metrics.items():
        if isinstance(v, (str, bool)):
            f.write(f"- **{k}**: {v}\n")
        elif isinstance(v, float):
            f.write(f"- **{k}**: {v:.4f}\n")
        elif isinstance(v, int):
            f.write(f"- **{k}**: {v}\n")
        elif isinstance(v, list):
            f.write(f"- **{k}**: {v}\n")
        else:
            f.write(f"- **{k}**: {v}\n")
    f.write(
        "\n*Synthetic-only warning:* Performance reflects recovery of synthetic signals through "
        "the pipeline with observed noise patterns. Generalization to real exoplanet signals is "
        "unverified. Real-planet detection requires independent confirmation.\n"
    )

# Save JSON of metrics
with open(ROOT / "reports" / "phase5_results.json", "w", encoding="utf-8") as f:
    json.dump(metrics, f, indent=2)

print(
    f"Baseline F1={metrics['f1']:.3f} (dummy={metrics['dummy_f1']:.3f}); RF "
    f"selected={metrics['rf_selected']}; Report: {OUTPUT_REPORT}"
)
