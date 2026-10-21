"""Phase 8 — corrected evaluation: train-only fit, validation-only selection, one test pass.

Differences from `scripts/phase5_baseline.py` (fixed here, nothing else changed):

1. Model/threshold selection uses validation data only. The Phase 5 script compared
   the RandomForest *validation* F1 against the baseline *test* F1
   (`phase5_baseline.py:146-148`), which lets the test score influence model choice.
2. The split is recorded per row by `phase8_features.py` instead of being recomputed
   from a global RNG inside the evaluation.
3. Imputation is fitted on train only (see phase8_features.py).

Writes `<out>/phase8_results.json` and `<out>/phase8_results.md`.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from phase8_features import FEATURE_NAMES  # noqa: E402
from phase8_split import SPLIT_SEED, assign_splits  # noqa: E402

PHASE8_SEED = 4242  # new experiment seed for any stochastic component


def _split_column(df):
    if "split" in df.columns:
        return df["split"].to_numpy()
    split, _ = assign_splits(df["segment_id"].values)
    return split


def evaluate(features_path, out_dir):
    df = pd.read_csv(features_path)
    split = _split_column(df)
    df = df.assign(_split=split)

    X = df[FEATURE_NAMES].to_numpy(float)
    y = df["label"].to_numpy(int)
    seg = df["segment_id"].to_numpy(int)

    masks = {name: df["_split"].to_numpy() == name for name in ("train", "val", "test")}
    for name, mask in masks.items():
        if mask.sum() == 0:
            raise SystemExit(f"empty {name} split")

    Xtr, ytr = X[masks["train"]], y[masks["train"]]
    Xva, yva = X[masks["val"]], y[masks["val"]]
    Xte, yte = X[masks["test"]], y[masks["test"]]

    model = LogisticRegression(max_iter=1000, C=1.0)
    model.fit(Xtr, ytr)

    pva = model.predict_proba(Xva)[:, 1]
    fpr, tpr, thresholds = roc_curve(yva, pva)
    best_idx = int(np.argmax(tpr - fpr))
    threshold = float(thresholds[best_idx])

    f1_val_baseline = float(f1_score(yva, (pva >= threshold).astype(int), zero_division=0))

    pte = model.predict_proba(Xte)[:, 1]
    yhat = (pte >= threshold).astype(int)
    cm = confusion_matrix(yte, yhat, labels=[0, 1])

    dummy = DummyClassifier(strategy="stratified", random_state=PHASE8_SEED)
    dummy.fit(Xtr, ytr)

    rf = RandomForestClassifier(n_estimators=200, max_depth=6, random_state=PHASE8_SEED)
    rf.fit(Xtr, ytr)
    rf_f1_val = float(f1_score(yva, rf.predict(Xva), zero_division=0))
    rf_selected = bool(rf_f1_val > f1_val_baseline + 0.05)  # validation vs validation

    metrics = {
        "threshold": threshold,
        "precision": float(precision_score(yte, yhat, zero_division=0)),
        "recall": float(recall_score(yte, yhat, zero_division=0)),
        "f1": float(f1_score(yte, yhat, zero_division=0)),
        "accuracy": float(accuracy_score(yte, yhat)),
        "confusion_matrix": cm.tolist(),
        "roc_auc": float(roc_auc_score(yte, pte)) if len(np.unique(yte)) > 1 else float("nan"),
        "pr_auc": float(average_precision_score(yte, pte))
        if len(np.unique(yte)) > 1
        else float("nan"),
        "splits": {
            name: {
                "windows": int(mask.sum()),
                "parent_groups": int(len(np.unique(seg[mask]))),
                "positive": int(y[mask].sum()),
                "negative": int((y[mask] == 0).sum()),
            }
            for name, mask in masks.items()
        },
        "f1_val_baseline": f1_val_baseline,
        "dummy_f1_val": float(f1_score(yva, dummy.predict(Xva), zero_division=0)),
        "rf_f1_validation": rf_f1_val,
        "rf_selected": rf_selected,
        "rf_f1_test": float(f1_score(yte, rf.predict(Xte), zero_division=0))
        if rf_selected
        else None,
        "dummy_f1_test": float(f1_score(yte, dummy.predict(Xte), zero_division=0)),
        "seed": {"split": SPLIT_SEED, "experiment": PHASE8_SEED},
        "features": FEATURE_NAMES,
        "feature_source": "presented window flux",
        "label_source": "synthetic injection only; no real-planet labels",
        "no_discovery_claim": True,
        "synthetic_only_warning": (
            "Measured on 26 simulated windows (7 test). "
            "Generalization to real observations is unverified."
        ),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase8_results.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )

    s = metrics["splits"]
    lines = [
        "# Phase 8 — Corrected Evaluation (presented-flux features)",
        "",
        "**Synthetic labels only; 26 windows total, 7 in test. Not a discovery claim.**",
        "",
        "## Protocol",
        "",
        "- Split: segment-level, shuffle `RandomState(42)`, cut 50/25/25 — unchanged from Phase 5.",
        "- Model: LogisticRegression(C=1.0, max_iter=1000) fitted on train only.",
        "- Threshold: Youden index on validation predictions only.",
        "- Test set: scored once, after all choices were fixed.",
        f"- RandomForest(n=200, max_depth=6, random_state={PHASE8_SEED}) "
        "compared on **validation** F1.",
        "- Imputation median fitted on train rows only.",
        "",
        "## Splits",
        "",
        "| split | windows | parent groups | positive | negative |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in ("train", "val", "test"):
        lines.append(
            f"| {name} | {s[name]['windows']} | {s[name]['parent_groups']} | "
            f"{s[name]['positive']} | {s[name]['negative']} |"
        )
    lines += [
        "",
        "## Test metrics",
        "",
        f"- threshold: {threshold:.4f}",
        f"- precision: {metrics['precision']:.4f}",
        f"- recall: {metrics['recall']:.4f}",
        f"- F1: {metrics['f1']:.4f}",
        f"- accuracy: {metrics['accuracy']:.4f}",
        f"- ROC-AUC: {metrics['roc_auc']:.4f}",
        f"- PR-AUC: {metrics['pr_auc']:.4f}",
        f"- confusion matrix (rows=true 0/1): {cm.tolist()}",
        f"- stratified dummy F1 (test): {metrics['dummy_f1_test']:.4f}",
        f"- RandomForest validation F1: {rf_f1_val:.4f} "
        f"(baseline validation F1 {f1_val_baseline:.4f}) → selected: {rf_selected}",
        "",
        "## Caveats",
        "",
        "- Seven test windows: one different classification moves F1 by ±0.1 or more.",
        "- Features are computed from simulated flux; real-observation performance is unknown.",
        "- No formal significance claim is made.",
    ]
    (out_dir / "phase8_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        f"Phase 8 eval: threshold={threshold:.4f} F1={metrics['f1']:.4f} "
        f"ROC-AUC={metrics['roc_auc']:.4f} PR-AUC={metrics['pr_auc']:.4f}"
    )
    print(f"Splits: { {k: v['windows'] for k, v in s.items()} }")
    print(f"Output: {out_dir / 'phase8_results.json'}")
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", default=str(ROOT / "reports" / "phase8_features.csv"))
    parser.add_argument("--out", default=str(ROOT / "reports"))
    args = parser.parse_args()
    evaluate(args.features, Path(args.out))
