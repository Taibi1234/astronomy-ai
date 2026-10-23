"""Phase 10 experiment: injection-recovery campaign and detection benchmark.

Everything is driven by an explicit config; nothing runs unless triggered through
the API or the CLI. Artifacts are written to a dedicated directory and never
overwrite Phase 5 or Phase 9 files.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
import transit_injection as ti
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from . import core, reports
from .features import time_domain_features  # re-export: shared builder, design §5.1

EXPERIMENT_VERSION = "1.0.0"

CONFIGS = {
    "smoke": {
        "label": "smoke",
        "datasets": ["kepler", "tess"],
        "chunks": {"kepler": 3, "tess": 3},
        "depths_ppm": [0, 150, 300],
        "noise_conditions": ["observed"],
        "offset_draws": 1,
        "seed": core.SEED,
    },
    "full": {
        "label": "full",
        "datasets": ["kepler", "tess"],
        "chunks": {"kepler": 3, "tess": 4},
        "depths_ppm": [0, 75, 150, 225, 300],
        "noise_conditions": ["observed", "amplified_x2"],
        "offset_draws": 2,
        "seed": core.SEED,
    },
}

FEATURE_NAMES = [
    "min_depth_ppm",
    "std_ppm",
    "mad_ppm",
    "gap_fraction",
    "mean_flux",
    "n_points",
]


def _split_map(chunk_ids: list[str], rng: np.random.Generator) -> dict[str, str]:
    """Grouped split by contiguous chunk; chunks never cross splits."""
    order = np.array(sorted(chunk_ids))
    rng.shuffle(order)
    n = len(order)
    split = {}
    for i, cid in enumerate(order):
        if i < n // 2:
            split[cid] = "train"
        elif i < 3 * n // 4:
            split[cid] = "val"
        else:
            split[cid] = "test"
    return split


def _thresholds(trials: pd.DataFrame) -> dict:
    """Control-derived detection threshold per (dataset, noise), fitted on TRAIN only."""
    out = {}
    for (dataset, noise), group in trials.groupby(["dataset", "noise_condition"]):
        controls = group[(group["requested_depth_ppm"] == 0) & (group["split"] != "test")]
        key = f"{dataset}|{noise}"
        if len(controls) >= 2:
            out[key] = {
                "threshold_snr": float(max(3.0, np.percentile(controls["snr"], 95))),
                "source": "max(3 sigma, 95th percentile of non-test controls)",
                "n_calibration_controls": int(len(controls)),
            }
        else:
            out[key] = {
                "threshold_snr": 3.0,
                "source": "fallback: 3-sigma (fewer than 2 calibration controls)",
                "n_calibration_controls": int(len(controls)),
            }
    return out


def _metric_block(y_true, y_pred, y_score) -> dict:
    """Metrics with explicit None where a metric is undefined for the sample."""
    y_true = np.asarray(y_true)
    out = {
        "n": int(len(y_true)),
        "positive": int(np.sum(y_true == 1)),
        "negative": int(np.sum(y_true == 0)),
    }
    prevalence = float(np.mean(y_true == 1))
    out["prevalence"] = prevalence
    out["f1_no_skill_predict_all_positive"] = (
        float(2 * prevalence / (1 + prevalence)) if prevalence > 0 else None
    )
    if len(np.unique(y_true)) < 2:
        out.update(
            {
                "precision": None,
                "recall": None,
                "f1": None,
                "roc_auc": None,
                "pr_auc": None,
                "confusion_matrix": None,
                "note": "single-class evaluation set; ranking metrics undefined",
            }
        )
        return out
    out.update(
        {
            "precision": float(precision_score(y_true, y_pred, zero_division=0)),
            "recall": float(recall_score(y_true, y_pred, zero_division=0)),
            "f1": float(f1_score(y_true, y_pred, zero_division=0)),
            "roc_auc": float(roc_auc_score(y_true, y_score)),
            "pr_auc": float(average_precision_score(y_true, y_score)),
            "confusion_matrix": confusion_matrix(y_true, y_pred, labels=[0, 1]).tolist(),
        }
    )
    return out


def _youden_threshold(y_true, scores) -> float:
    fpr, tpr, thresholds = roc_curve(y_true, scores)
    idx = int(np.argmax(tpr - fpr))
    return float(thresholds[idx])


def run_experiment(  # noqa: C901, PLR0912, PLR0915 - orchestration is linear by design
    mode: str = "smoke",
    out_dir: Path | None = None,
    progress=None,
    dataset_loader=None,
) -> dict:
    """Execute the campaign and write artifacts. Returns the summary dict."""
    if mode not in CONFIGS:
        raise ValueError(f"unknown mode: {mode}")

    started = core.utc_now()
    t0 = time.time()
    cfg = dict(CONFIGS[mode])
    cfg["tolerance_days"] = core.TOLERANCE_DAYS
    cfg["search_half_days"] = core.SEARCH_HALF_DAYS
    cfg["search_step_days"] = core.SEARCH_STEP_DAYS
    cfg["features"] = FEATURE_NAMES

    root = Path(__file__).resolve().parents[3]
    out_dir = Path(out_dir) if out_dir else root / "reports" / "injection_recovery"
    out_dir.mkdir(parents=True, exist_ok=True)

    load = dataset_loader or core.load_curve
    curves = {m: load(m) for m in cfg["datasets"]}
    source_hashes = {}
    for m in cfg["datasets"]:
        path = (
            root
            / "data"
            / "processed"
            / ("kepler_kepler_10.csv" if m == "kepler" else "tess_kepler_10.csv")
        )
        source_hashes[m] = hashlib.sha256(path.read_bytes()).hexdigest()

    rng = np.random.default_rng(cfg["seed"])

    # Split chunks per dataset (grouped; chunk is the independent unit).
    splits = {}
    chunks = {}
    for m in cfg["datasets"]:
        times, _ = curves[m]
        ch = core.make_chunks(times, m, cfg["chunks"][m])
        chunks[m] = ch
        splits[m] = _split_map([c.chunk_id for c in ch], rng)

    # Hidden phase offsets, drawn once per (chunk, offset draw) and reused across
    # depths and noise conditions so comparisons are paired.
    deltas = {}
    for m in cfg["datasets"]:
        for c in chunks[m]:
            for k in range(cfg["offset_draws"]):
                deltas[(c.chunk_id, k)] = float(rng.uniform(-0.10, 0.10))

    total_trials = sum(
        len(chunks[m]) * cfg["offset_draws"] * len(cfg["depths_ppm"]) * len(cfg["noise_conditions"])
        for m in cfg["datasets"]
    )
    done = 0
    rows = []

    for m in cfg["datasets"]:
        times_all, flux_all = curves[m]
        for chunk in chunks[m]:
            sl = slice(chunk.start_index, chunk.end_index)
            t = np.asarray(times_all[sl], dtype=float)
            f0 = np.asarray(flux_all[sl], dtype=float)
            immutable = f0.copy()

            for k in range(cfg["offset_draws"]):
                delta_true = deltas[(chunk.chunk_id, k)]
                for noise in cfg["noise_conditions"]:
                    cleaned, _ = core.remove_published_transit(t, immutable, m)
                    base = core.apply_noise_condition(cleaned, noise)
                    for depth in cfg["depths_ppm"]:
                        trial_id = f"{chunk.chunk_id}-o{k}-{noise}-d{depth}"
                        started_trial = core.utc_now()

                        valid, reason = True, ""
                        if len(t) < core.MIN_CHUNK_POINTS:
                            valid, reason = False, "insufficient observations in chunk"

                        if valid and depth > 0:
                            dt = core.phase_offsets(t, m, delta_true)
                            presented = ti.inject_transit(base, dt, float(depth))
                        elif valid:
                            presented = base.copy()
                        else:
                            presented = base.copy()

                        if not np.array_equal(immutable, f0):
                            raise RuntimeError("source chunk was mutated")

                        det = (
                            core.detect(t, presented, m)
                            if valid
                            else {
                                "snr": float("nan"),
                                "delta": float("nan"),
                                "depth_ppm": float("nan"),
                                "sigma_ppm": float("nan"),
                            }
                        )
                        feats = time_domain_features(t, presented)

                        rows.append(
                            {
                                "trial_id": trial_id,
                                "dataset": m,
                                "chunk_id": chunk.chunk_id,
                                "split": splits[m][chunk.chunk_id],
                                "noise_condition": noise,
                                "offset_index": k,
                                "requested_depth_ppm": float(depth),
                                "injected": bool(depth > 0),
                                "delta_true_days": float(delta_true),
                                "delta_est_days": float(det["delta"]),
                                "timing_error_days": float(abs(det["delta"] - delta_true)),
                                "snr": float(det["snr"]),
                                "sigma_ppm": float(det["sigma_ppm"]),
                                "depth_est_ppm": float(det["depth_ppm"]),
                                "n_points": int(len(t)),
                                "valid": valid,
                                "invalid_reason": reason,
                                "started_at": started_trial,
                                **feats,
                            }
                        )

                        done += 1
                        if progress:
                            progress(done, total_trials)

    trials = pd.DataFrame(rows)

    # Thresholds from train-split controls only.
    thresholds = _thresholds(trials)

    def _thr(dataset, noise):
        return thresholds[f"{dataset}|{noise}"]["threshold_snr"]

    trials["threshold_snr"] = [
        _thr(d, n) for d, n in zip(trials["dataset"], trials["noise_condition"], strict=False)
    ]
    trials["detected"] = trials["snr"] > trials["threshold_snr"]
    trials["recovered"] = (
        trials["injected"]
        & trials["detected"]
        & (trials["timing_error_days"] <= core.TOLERANCE_DAYS)
    )
    trials["false_positive"] = (~trials["injected"]) & trials["detected"]

    # --- Recovery tables -----------------------------------------------------
    def recovery_table(frame: pd.DataFrame) -> list[dict]:
        rows_out = []
        for depth, group in frame[frame["injected"]].groupby("requested_depth_ppm"):
            k = int(group["recovered"].sum())
            n = int(len(group))
            ci = core.wilson_interval(k, n)
            rows_out.append(
                {
                    "requested_depth_ppm": float(depth),
                    "recovered": k,
                    "trials": n,
                    "fraction": (k / n) if n else None,
                    "wilson_low": ci["low"],
                    "wilson_high": ci["high"],
                    "median_recovered_depth_ppm": (
                        float(group.loc[group["recovered"], "depth_est_ppm"].median())
                        if k
                        else None
                    ),
                    "median_timing_error_days": (
                        float(group["timing_error_days"].median()) if n else None
                    ),
                }
            )
        return sorted(rows_out, key=lambda r: r["requested_depth_ppm"])

    recovery_all = recovery_table(trials[trials["valid"]])
    recovery_test = recovery_table(trials[(trials["valid"]) & (trials["split"] == "test")])

    control_eval = trials[(~trials["injected"]) & (trials["split"] == "test")]
    fp = int(control_eval["false_positive"].sum())
    fp_ci = core.wilson_interval(fp, int(len(control_eval)))

    by_dataset = []
    for (dataset, noise), group in trials[trials["injected"] & trials["valid"]].groupby(
        ["dataset", "noise_condition"]
    ):
        k, n = int(group["recovered"].sum()), int(len(group))
        ci = core.wilson_interval(k, n)
        by_dataset.append(
            {
                "dataset": dataset,
                "noise_condition": noise,
                "recovered": k,
                "trials": n,
                "fraction": (k / n) if n else None,
                "wilson_low": ci["low"],
                "wilson_high": ci["high"],
            }
        )

    # --- Detection benchmark -------------------------------------------------
    benchmark = _benchmark(trials, thresholds)

    finished = core.utc_now()
    elapsed = time.time() - t0

    summary = {
        "experiment": "phase10-injection-recovery",
        "version": EXPERIMENT_VERSION,
        "mode": mode,
        "status": "completed",
        "started_at": started,
        "finished_at": finished,
        "runtime_seconds": round(elapsed, 2),
        "config": cfg,
        "counts": {
            "trials_total": int(len(trials)),
            "trials_valid": int(trials["valid"].sum()),
            "trials_invalid": int((~trials["valid"]).sum()),
            "controls_evaluated_for_fpr": int(len(control_eval)),
            "chunks": {m: len(chunks[m]) for m in cfg["datasets"]},
            "splits": {
                m: {
                    "chunks": {
                        s: sum(1 for v in splits[m].values() if v == s)
                        for s in ("train", "val", "test")
                    },
                }
                for m in cfg["datasets"]
            },
        },
        "excluded_trials": [
            {"reason": str(r), "count": int((trials["invalid_reason"] == r).sum())}
            for r in trials.loc[~trials["valid"], "invalid_reason"].unique()
        ],
        "thresholds": thresholds,
        "recovery_by_depth_all_splits": recovery_all,
        "recovery_by_depth_test_split": recovery_test,
        "recovery_by_dataset_and_noise": by_dataset,
        "false_positive_rate": {
            "controls": int(len(control_eval)),
            "false_positives": fp,
            "rate": (fp / len(control_eval)) if len(control_eval) else None,
            "wilson_low": fp_ci["low"],
            "wilson_high": fp_ci["high"],
            "definition": "zero-depth trials in test-split chunks (never used for calibration)",
        },
        "benchmark": benchmark,
        "limitations": [
            "Independent units are contiguous chunks (3-4 per dataset), not individual cadences.",
            "Injections are coherent across each chunk's transits, at a hidden "
            "phase offset from the published ephemeris.",
            "Synthetic injection recovery does not establish real-planet detection performance.",
            "The ML benchmark uses six time-domain features and very few "
            "independent groups; treat it as exploratory.",
        ],
        "provenance": {
            "source_hashes": source_hashes,
            "seed": cfg["seed"],
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "packages": {
                "numpy": np.__version__,
                "pandas": pd.__version__,
                "scikit-learn": sklearn.__version__,
                "batman": getattr(__import__("batman"), "__version__", "unknown"),
            },
            "git_commit": _git_commit(root),
            "command": f"python -m research.run_experiment --mode {mode}",
        },
        "artifacts": {
            "trial_results": "trial_results.csv",
            "summary": "summary.json",
            "config": "config.json",
            "plot_data": "plot_data.json",
            "report": "recovery_report.md",
        },
    }

    core.write_json(out_dir / "config.json", cfg)
    core.write_json(out_dir / "provenance.json", summary["provenance"])
    trials.to_csv(out_dir / "trial_results.csv", index=False)
    core.write_json(out_dir / "summary.json", summary)

    plot_data = reports.plot_data_from_summary(summary, trials)
    core.write_json(out_dir / "plot_data.json", plot_data)
    reports.write_figures(plot_data, out_dir / "figures")
    reports.write_markdown(summary, plot_data, out_dir / "recovery_report.md")

    return summary


def _benchmark(  # noqa: C901, PLR0912, PLR0915
    trials: pd.DataFrame, thresholds: dict
) -> dict:
    """Physics detector vs LR vs RF on the same grouped test chunks."""
    data = trials[trials["valid"]].copy()
    X = data[FEATURE_NAMES].to_numpy(dtype=float)
    y = data["injected"].to_numpy(dtype=int)
    split = data["split"].to_numpy()

    train, val, test = split == "train", split == "val", split == "test"
    result = {
        "features": FEATURE_NAMES,
        "splits": {
            name: {
                "windows": int(mask.sum()),
                "groups": int(data.loc[mask, "chunk_id"].nunique()),
                "positive": int(y[mask].sum()),
                "negative": int((y[mask] == 0).sum()),
            }
            for name, mask in (("train", train), ("val", val), ("test", test))
        },
        "methods": {},
        "notes": [
            "All methods are evaluated on the same test chunks and labels.",
            "The physics detector's threshold is calibrated on train-split controls only.",
            "ML preprocessing (scaling, imputation) is fitted on train rows only.",
        ],
    }

    # Physics
    physics_score = data["snr"].to_numpy(dtype=float)
    physics_pred = data["detected"].to_numpy(dtype=int)
    result["methods"]["physics_matched_filter"] = _metric_block(
        y[test], physics_pred[test], physics_score[test]
    )

    if test.sum() == 0 or train.sum() == 0 or val.sum() == 0:
        result["status"] = "insufficient_groups"
        result["reason"] = "train, validation and test chunks are all required"
        return result

    # Imputation fitted on train only.
    medians = np.nanmedian(X[train], axis=0)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    X = np.where(np.isfinite(X), X, medians)

    lr = Pipeline(
        [
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, C=1.0, random_state=0)),
        ]
    )
    lr.fit(X[train], y[train])
    lr_val = lr.predict_proba(X[val])[:, 1]
    lr_test = lr.predict_proba(X[test])[:, 1]

    if len(np.unique(y[val])) > 1:
        thr = _youden_threshold(y[val], lr_val)
    else:
        thr = 0.5
    result["logistic_threshold"] = {"value": float(thr), "selected_on": "validation only"}

    lr_block = _metric_block(y[test], (lr_test >= thr).astype(int), lr_test)
    if len(np.unique(y[test])) > 1:
        lr_block["brier"] = float(brier_score_loss(y[test], lr_test))
    result["methods"]["logistic_regression"] = lr_block

    rf = RandomForestClassifier(n_estimators=200, max_depth=6, random_state=42)
    rf.fit(X[train], y[train])
    rf_val_f1 = float(f1_score(y[val], rf.predict(X[val]), zero_division=0))
    lr_val_f1 = float(f1_score(y[val], (lr_val >= thr).astype(int), zero_division=0))
    rf_selected = bool(rf_val_f1 > lr_val_f1 + 0.05)
    rf_block = _metric_block(y[test], rf.predict(X[test]), rf.predict_proba(X[test])[:, 1])
    rf_block["selected"] = rf_selected
    rf_block["validation_f1"] = rf_val_f1
    rf_block["baseline_validation_f1"] = lr_val_f1
    result["methods"]["random_forest"] = rf_block

    dummy = DummyClassifier(strategy="stratified", random_state=42)
    dummy.fit(X[train], y[train])
    result["methods"]["dummy"] = _metric_block(
        y[test], dummy.predict(X[test]), dummy.predict_proba(X[test])[:, 1]
    )

    # Per-depth recovery on the test split, physics vs LR.
    per_depth = []
    test_data = data[test]
    for depth, group in test_data[test_data["injected"]].groupby("requested_depth_ppm"):
        local = test_data.index.get_indexer(group.index)
        lr_hits = int((lr_test[local] >= thr).sum())
        per_depth.append(
            {
                "requested_depth_ppm": float(depth),
                "trials": int(len(group)),
                "physics_recovered": int(group["recovered"].sum()),
                "logistic_detected": lr_hits,
            }
        )
    result["per_depth_test"] = sorted(per_depth, key=lambda r: r["requested_depth_ppm"])

    result["status"] = "ok"
    return result


def _git_commit(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or None
    except Exception:
        return None
