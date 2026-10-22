"""Phase 11a: frozen split, window rules, null library, and experiment config.

This module only *materializes the pre-registered plan*. It never injects a
transit, never calls the detector, and never fits a model: generating the
manifests is pure, deterministic bookkeeping over the quarter light curves.

Design decisions frozen here (see reports/phase11_research_plan.md):

* The split cluster is the Kepler quarter. Every window inherits its quarter's
  partition, so a quarter can never appear in two splits.
* Windows are laid consecutively inside each contiguous piece of a quarter and
  never span a data gap longer than ``MAJOR_GAP_DAYS``.
* Each window is either an *injection* window (injected depths + a paired
  zero-depth control) or a *null* window (depth 0 only). Roles are assigned in
  consecutive pairs inside each quarter by a deterministic SHA-256 coin keyed on
  the quarter id, pair index and window length — never on flux, noise, labels,
  detector scores or test performance — with an odd tail decided by its own coin.
  The two roles therefore never share cadences, and per-quarter counts stay
  balanced to within one window.
* Null windows in train+validation quarters calibrate the detector threshold;
  null windows in test quarters measure the false-positive rate. Paired controls
  are used for paired comparisons only and are excluded from both.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

PERIOD_DAYS = 0.837491225  # Kepler-10 b, published ephemeris (same value as transit_injection)

# --- frozen split ------------------------------------------------------------

SPLIT_SEED = 20261022
OFFSET_SEED = 20261023
SPLIT_QUOTAS = {"train": 7, "val": 3, "test": 5}

SPLIT_ASSIGNMENT = {
    "Q00": "train",
    "Q01": "val",
    "Q02": "test",
    "Q03": "train",
    "Q04": "train",
    "Q05": "train",
    "Q06": "val",
    "Q07": "train",
    "Q09": "test",
    "Q10": "val",
    "Q11": "train",
    "Q13": "test",
    "Q14": "test",
    "Q15": "train",
    "Q17": "test",
}

# --- window rules ------------------------------------------------------------

WINDOW_DAYS = {"primary": 5.0, "sensitivity": 3.0}
MAJOR_GAP_DAYS = 1.0
MIN_WINDOW_POINTS = 40
MIN_WINDOW_FRACTION = 0.8
MIN_TRANSITS = 2.0
SHORT_QUARTER_DAYS = 60.0

# --- injection design --------------------------------------------------------

INJECTION_DEPTHS_PPM = (50.0, 75.0, 100.0, 150.0, 300.0)
CONTROL_DEPTH_PPM = 0.0
OFFSET_DRAWS = 2
OFFSET_HALF_DAYS = 0.10
NOISE_CONDITIONS = ("observed", "amplified_x2")
TARGET_FPR = 0.05

# --- feature sets (no model is fitted in Phase 11a) ---------------------------

FORBIDDEN_FEATURE_COLUMNS = (
    "trial_id",
    "window_id",
    "quarter",
    "split",
    "role",
    "requested_depth_ppm",
    "injected",
    "delta_true_days",
    "recovered",
    "detected",
    "false_positive",
    "threshold_snr",
    "valid",
    "invalid_reason",
    "timing_error_days",
)

DETECTOR_OUTPUTS = ("snr", "depth_est_ppm", "sigma_ppm")
FLUX_FEATURES_FULL = (
    "min_depth_ppm",
    "std_ppm",
    "mad_ppm",
    "gap_fraction",
    "mean_flux",
    "n_points",
)
FLUX_FEATURES_NO_DEPTH_PROXY = tuple(f for f in FLUX_FEATURES_FULL if f != "min_depth_ppm")
FLUX_FEATURES_CLEAN = tuple(
    f for f in FLUX_FEATURES_FULL if f not in ("min_depth_ppm", "n_points", "gap_fraction")
)

ML_LADDER = (
    {
        "id": "L0_no_skill_all_positive",
        "kind": "analytic",
        "features": (),
        "note": "predicts positive for every window; F1 = 2p/(1+p)",
    },
    {
        "id": "L1_dummy_stratified",
        "kind": "model",
        "features": (),
        "note": "sklearn DummyClassifier(strategy='stratified') on train prevalence",
    },
    {
        "id": "L2_snr_only",
        "kind": "model",
        "features": ("snr",),
        "note": "matched-filter S/N alone; no ML required",
    },
    {
        "id": "L3_detector_outputs",
        "kind": "model",
        "features": DETECTOR_OUTPUTS,
        "note": "detector measurements only, all derived from the presented flux",
    },
    {
        "id": "L4_flux_full",
        "kind": "model",
        "features": FLUX_FEATURES_FULL,
        "note": "Phase 10 features; includes the min_depth_ppm depth proxy and group identifiers",
    },
    {
        "id": "L5_flux_without_depth_proxy",
        "kind": "model",
        "features": FLUX_FEATURES_NO_DEPTH_PROXY,
        "note": "drops min_depth_ppm only: the pre-registered with/without comparison",
    },
    {
        "id": "L6_flux_clean",
        "kind": "model",
        "features": FLUX_FEATURES_CLEAN,
        "note": "drops min_depth_ppm and the per-window group identifiers",
    },
    {
        "id": "L7_detector_plus_clean_flux",
        "kind": "model",
        "features": DETECTOR_OUTPUTS + FLUX_FEATURES_CLEAN,
        "note": "detector measurements plus group-identifier-free flux features",
    },
)

# measured on Phase 10 artifacts: t = intercept + slope * n_points (seconds)
COST_MODEL_INTERCEPT_S = 0.019
COST_MODEL_SLOPE_S_PER_POINT = 1.76e-05

FEASIBILITY_MINIMUMS = {
    "injection_windows": {"train": 20, "val": 10, "test": 20},
    "null_windows": {"train": 20, "val": 10, "test": 20},
    "positives_per_depth_per_split": 50,
    "per_depth_balance_range": (0.40, 0.60),
}


@dataclass(frozen=True)
class Window:
    """One non-overlapping window inside a contiguous piece of one quarter."""

    quarter: str
    split: str
    role: str
    piece_index: int
    window_index: int
    start_index: int
    end_index: int
    time_start: float
    time_end: float
    n_points: int
    transits: float


def project_root() -> Path:
    """app.py-style anchor: research/ -> backend/ -> webapp/ -> repository root."""
    return Path(__file__).resolve().parents[3]


def quarter_files(root: Path | None = None) -> dict[str, Path]:
    """Map quarter id -> file, sorted, so manifest order never depends on the OS."""
    base = (root or project_root()) / "data" / "processed"
    files = sorted(base.glob("kepler_q*_quality_masked.csv"), key=lambda p: p.name)
    mapping = {}
    for path in files:
        quarter = path.name.split("_")[1].upper()
        mapping[quarter] = path
    if not mapping:
        raise FileNotFoundError(f"no quarter files found under {base}")
    return mapping


def _optional_sha256(path: Path) -> str | None:
    """Hash of an input file that may be absent on a partial checkout."""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def load_quarter(path: Path) -> tuple[np.ndarray, np.ndarray, int]:
    """Times and flux sorted by time; non-finite rows dropped deterministically."""
    frame = pd.read_csv(path, usecols=["time", "normalized_flux"])
    times = pd.to_numeric(frame["time"], errors="coerce").to_numpy(dtype=float)
    flux = pd.to_numeric(frame["normalized_flux"], errors="coerce").to_numpy(dtype=float)
    keep = np.isfinite(times) & np.isfinite(flux)
    excluded = int(len(frame) - keep.sum())
    times, flux = times[keep], flux[keep]
    order = np.argsort(times, kind="stable")
    return times[order], flux[order], excluded


def contiguous_pieces(times: np.ndarray, gap_days: float = MAJOR_GAP_DAYS) -> list[tuple[int, int]]:
    """Index ranges separated by data gaps longer than ``gap_days``."""
    if len(times) < 2:
        return [(0, len(times))]
    cuts = np.flatnonzero(np.diff(times) > gap_days) + 1
    bounds = [0, *cuts.tolist(), len(times)]
    return [(int(bounds[i]), int(bounds[i + 1])) for i in range(len(bounds) - 1)]


def _is_valid_window(times: np.ndarray, window_days: float) -> bool:
    if len(times) < MIN_WINDOW_POINTS:
        return False
    duration = float(times[-1] - times[0])
    return duration >= MIN_WINDOW_FRACTION * window_days and duration / PERIOD_DAYS >= MIN_TRANSITS


def generate_windows(
    times: np.ndarray, quarter: str, window_days: float
) -> list[Window]:
    """Consecutive, non-overlapping windows inside each contiguous piece.

    A window starts at the first cadence of a piece (or where the previous window
    ended) and covers ``window_days`` of time. Partial tails are kept only when
    they satisfy the pre-registered minimum duration/occupancy.
    """
    split = SPLIT_ASSIGNMENT[quarter]
    windows: list[Window] = []
    for piece_index, (lo, hi) in enumerate(contiguous_pieces(times)):
        piece = times[lo:hi]
        if piece.size < MIN_WINDOW_POINTS:
            continue
        start_time = float(piece[0])
        while start_time + window_days <= float(piece[-1]) + 1e-9:
            stop_time = start_time + window_days
            mask = (piece >= start_time) & (piece < stop_time)
            chosen = piece[mask]
            if _is_valid_window(chosen, window_days):
                first = int(np.flatnonzero(mask)[0]) + lo
                last = int(np.flatnonzero(mask)[-1]) + lo
                windows.append(
                    Window(
                        quarter=quarter,
                        split=split,
                        role="pending",
                        piece_index=piece_index,
                        window_index=len(windows),
                        start_index=first,
                        end_index=last + 1,
                        time_start=float(times[first]),
                        time_end=float(times[last]),
                        n_points=int(last + 1 - first),
                        transits=round(float(times[last] - times[first]) / PERIOD_DAYS, 3),
                    )
                )
            start_time = stop_time
        tail = piece[piece >= start_time]
        if tail.size and _is_valid_window(tail, window_days):
            first = int(np.flatnonzero(piece >= start_time)[0]) + lo
            last = int(np.flatnonzero(piece >= start_time)[-1]) + lo
            windows.append(
                Window(
                    quarter=quarter,
                    split=split,
                    role="pending",
                    piece_index=piece_index,
                    window_index=len(windows),
                    start_index=first,
                    end_index=last + 1,
                    time_start=float(times[first]),
                    time_end=float(times[last]),
                    n_points=int(last + 1 - first),
                    transits=round(float(times[last] - times[first]) / PERIOD_DAYS, 3),
                )
            )

    return assign_roles(windows, window_days)


ROLE_COIN_VERSION = "phase11-role-v2"


def role_coin(quarter: str, draw: str, window_days: float) -> bool:
    """Deterministic coin from identifiers only (never flux, labels or scores).

    The key intentionally includes the window length so the 5-day and 3-day
    allocations are independent draws over different window inventories.
    """
    key = f"{ROLE_COIN_VERSION}|{quarter}|{draw}|{window_days:.2f}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 2 == 0


def assign_roles(windows: list[Window], window_days: float) -> list[Window]:
    """Paired deterministic injection/null allocation inside one quarter.

    Consecutive eligible windows are paired; one SHA-256 coin per pair decides
    which member is injected. An odd leftover window is decided by its own
    ``tail`` coin. This keeps per-quarter counts balanced (difference <= 1) while
    removing the systematic "earlier window is always injected" bias of a plain
    index-parity rule.

    Inputs are the quarter id, the pair/tail index and the window length only.
    """
    if not windows:
        return []
    quarters = {w.quarter for w in windows}
    if len(quarters) != 1:
        raise ValueError(f"assign_roles expects one quarter, got {sorted(quarters)}")

    ordered = sorted(windows, key=lambda w: (w.piece_index, w.window_index))
    roles: dict[int, str] = {}
    n_pairs = len(ordered) // 2
    for pair in range(n_pairs):
        first, second = ordered[2 * pair], ordered[2 * pair + 1]
        flip = role_coin(first.quarter, f"pair-{pair}", window_days)
        roles[first.window_index] = "injection" if flip else "null"
        roles[second.window_index] = "null" if flip else "injection"
    if len(ordered) % 2:
        tail = ordered[-1]
        roles[tail.window_index] = (
            "injection" if role_coin(tail.quarter, "tail", window_days) else "null"
        )

    return [replace(w, role=roles[w.window_index]) for w in windows]


def build_manifests(root: Path | None = None) -> dict[str, dict]:
    """Build the four pre-registered artifacts in memory (no side effects)."""
    root = root or project_root()
    files = quarter_files(root)
    missing = sorted(set(SPLIT_ASSIGNMENT) - set(files))
    extra = sorted(set(files) - set(SPLIT_ASSIGNMENT))
    if missing or extra:
        raise ValueError(f"quarter inventory mismatch: missing={missing} extra={extra}")

    quarters: dict[str, dict] = {}
    windows_by_length: dict[str, list[Window]] = {k: [] for k in WINDOW_DAYS}

    for quarter, path in files.items():
        times, _flux, excluded = load_quarter(path)
        pieces = contiguous_pieces(times)
        entry = {
            "file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "split": SPLIT_ASSIGNMENT[quarter],
            "rows": int(times.size),
            "excluded_non_finite": excluded,
            "span_days": round(float(times[-1] - times[0]), 6),
            "contiguous_pieces": len(pieces),
            "short": bool(times[-1] - times[0] < SHORT_QUARTER_DAYS),
        }
        for label, window_days in WINDOW_DAYS.items():
            windows = generate_windows(times, quarter, window_days)
            windows_by_length[label].extend(windows)
            entry[f"windows_{label}"] = len(windows)
            entry[f"injection_windows_{label}"] = sum(w.role == "injection" for w in windows)
            entry[f"null_windows_{label}"] = sum(w.role == "null" for w in windows)
        quarters[quarter] = entry

    split_manifest = {
        "phase": "11a",
        "unit_of_independence": "kepler quarter",
        "quotas": SPLIT_QUOTAS,
        "seed": SPLIT_SEED,
        "short_quarter_days": SHORT_QUARTER_DAYS,
        "assignment": dict(sorted(SPLIT_ASSIGNMENT.items())),
        "quarters": dict(sorted(quarters.items())),
    }

    window_manifests = {}
    for label, window_days in WINDOW_DAYS.items():
        window_manifests[label] = {
            "phase": "11a",
            "window_days": window_days,
            "rules": {
                "major_gap_days": MAJOR_GAP_DAYS,
                "min_points": MIN_WINDOW_POINTS,
                "min_duration_fraction": MIN_WINDOW_FRACTION,
                "min_transits": MIN_TRANSITS,
                "overlap": "none",
                "role_assignment": (
                    "paired SHA-256 coin per consecutive pair within a quarter; "
                    "odd tail uses its own coin"
                ),
                "role_coin_version": ROLE_COIN_VERSION,
                "role_inputs": ["quarter", "pair index", "window length"],
            },
            "windows": [asdict(w) for w in windows_by_length[label]],
        }

    null_library = {}
    for label in WINDOW_DAYS:
        by_split: dict[str, dict] = {}
        for split in ("train", "val", "test"):
            nulls = [w for w in windows_by_length[label] if w.split == split and w.role == "null"]
            injections = [
                w for w in windows_by_length[label] if w.split == split and w.role == "injection"
            ]
            by_split[split] = {
                "quarters": sorted({w.quarter for w in nulls}),
                "null_windows": len(nulls),
                "null_trials": len(nulls) * OFFSET_DRAWS * len(NOISE_CONDITIONS),
                "injection_windows": len(injections),
                "paired_control_trials": len(injections) * OFFSET_DRAWS * len(NOISE_CONDITIONS),
            }
        null_library[label] = {
            "phase": "11a",
            "target_fpr": TARGET_FPR,
            "calibration": {
                "splits": ["train", "val"],
                "quarters": sorted(
                    {w.quarter for w in windows_by_length[label] if w.split in ("train", "val")
                     and w.role == "null"}
                ),
                "null_windows": by_split["train"]["null_windows"] + by_split["val"]["null_windows"],
                "null_trials": by_split["train"]["null_trials"] + by_split["val"]["null_trials"],
            },
            "test": {
                "splits": ["test"],
                "quarters": by_split["test"]["quarters"],
                "null_windows": by_split["test"]["null_windows"],
                "null_trials": by_split["test"]["null_trials"],
            },
            "paired_controls": {
                "used_for": "paired recovery comparisons only",
                "excluded_from": ["threshold calibration", "false-positive rate"],
                "windows": sum(v["injection_windows"] for v in by_split.values()),
                "trials": sum(v["paired_control_trials"] for v in by_split.values()),
            },
            "by_split": by_split,
        }

    config = {
        "phase": "11a",
        "status": "frozen plan — campaign not executed, no model trained",
        "target": "Kepler-10 b",
        "unit_of_independence": "kepler quarter",
        "split": {
            "quotas": SPLIT_QUOTAS,
            "seed": SPLIT_SEED,
            "assignment": dict(sorted(SPLIT_ASSIGNMENT.items())),
        },
        "window": {
            "primary_days": WINDOW_DAYS["primary"],
            "sensitivity_days": WINDOW_DAYS["sensitivity"],
            "major_gap_days": MAJOR_GAP_DAYS,
            "min_points": MIN_WINDOW_POINTS,
            "min_duration_fraction": MIN_WINDOW_FRACTION,
            "min_transits": MIN_TRANSITS,
            "selection_rule": (
                "both lengths reported separately; neither selected on test performance"
            ),
        },
        "injection": {
            "depths_ppm": list(INJECTION_DEPTHS_PPM),
            "control_depth_ppm": CONTROL_DEPTH_PPM,
            "offset_draws": OFFSET_DRAWS,
            "offset_half_days": OFFSET_HALF_DAYS,
            "offset_seed": OFFSET_SEED,
            "noise_conditions": list(NOISE_CONDITIONS),
            "formula": "injected = flux + median(flux_window) * (batman_model - 1)",
        },
        "null_library": {
            "target_fpr": TARGET_FPR,
            "calibration_splits": ["train", "val"],
            "calibration_rule": (
                "max(3.0, 95th percentile of calibration null S/N) per noise condition"
            ),
            "evaluation_split": "test",
            "paired_controls_excluded_from": ["calibration", "false-positive rate"],
            "fpr_reporting": (
                "count, denominator, Wilson interval and cluster interval; no 1% target"
            ),
        },
        "ml_ladder": [
            {
                "id": entry["id"],
                "kind": entry["kind"],
                "features": list(entry["features"]),
                "note": entry["note"],
            }
            for entry in ML_LADDER
        ],
        "forbidden_feature_columns": list(FORBIDDEN_FEATURE_COLUMNS),
        "metrics": {
            "primary": ["roc_auc", "recall_at_calibrated_fpr"],
            "secondary": ["pr_auc_with_prevalence", "mcc", "balanced_accuracy", "brier"],
            "f1": "reported with prevalence and no-skill value; never used for selection",
            "intervals": "cluster bootstrap over quarters (BCa, 10000 resamples), k reported",
            "trial_level_wilson": "orientation only; labelled anti-conservative (design effect ~2)",
        },
        "sensitivity": {
            "primary": "5-day windows",
            "secondary": ["3-day windows", "exclude short quarters"],
            "short_quarter_days": SHORT_QUARTER_DAYS,
            "short_quarters": sorted(q for q, e in quarters.items() if e["short"]),
            "note": (
                "reported separately; the primary window length is never chosen on "
                "test performance"
            ),
        },
        "tess_case_study": {
            "included_in_split": False,
            "reason": (
                "one sector is one cluster: descriptive external check only, reported "
                "without a confidence interval"
            ),
            "file": "tess_kepler_10.csv",
            "sha256": _optional_sha256(root / "data" / "processed" / "tess_kepler_10.csv"),
        },
        "projected_cost": _projected_cost(windows_by_length),
    }

    return {
        "split.json": split_manifest,
        "windows_primary.json": window_manifests["primary"],
        "windows_sensitivity.json": window_manifests["sensitivity"],
        "null_library.json": null_library,
        "experiment_config.json": config,
    }


def _projected_cost(windows_by_length: dict[str, list[Window]]) -> dict:
    """Runtime projection from the cost model measured on Phase 10 (seconds)."""
    out = {}
    for label, windows in windows_by_length.items():
        injection = [w for w in windows if w.role == "injection"]
        nulls = [w for w in windows if w.role == "null"]
        injection_trials = len(injection) * (
            len(INJECTION_DEPTHS_PPM) * OFFSET_DRAWS * len(NOISE_CONDITIONS)
        )
        paired_trials = len(injection) * OFFSET_DRAWS * len(NOISE_CONDITIONS)
        null_trials = len(nulls) * OFFSET_DRAWS * len(NOISE_CONDITIONS)
        all_points = [w.n_points for w in windows]
        mean_points = float(np.mean(all_points)) if all_points else 0.0
        per_trial = COST_MODEL_INTERCEPT_S + COST_MODEL_SLOPE_S_PER_POINT * mean_points
        total_trials = injection_trials + paired_trials + null_trials
        out[label] = {
            "injection_trials": int(injection_trials),
            "paired_control_trials": int(paired_trials),
            "null_trials": int(null_trials),
            "total_detector_trials": int(total_trials),
            "mean_points_per_trial": round(mean_points, 1),
            "seconds_per_trial": round(per_trial, 4),
            "projected_seconds": round(total_trials * per_trial, 1),
            "model": "t = 0.019 s + 1.76e-05 s/point (measured on Phase 10 artifacts)",
        }
    return out


def feasibility_report(manifests: dict[str, dict]) -> dict:
    """Pre-registered viability checks; raises nothing, returns pass/fail per rule."""
    report: dict[str, dict] = {}
    lengths = (
        ("primary", "windows_primary.json"),
        ("sensitivity", "windows_sensitivity.json"),
    )
    for label, key in lengths:
        windows = manifests[key]["windows"]
        rows: dict[str, dict] = {}
        ok = True
        for split in ("train", "val", "test"):
            subset = [w for w in windows if w["split"] == split]
            injections = [w for w in subset if w["role"] == "injection"]
            nulls = [w for w in subset if w["role"] == "null"]
            per_condition = OFFSET_DRAWS * len(NOISE_CONDITIONS)
            positives = len(injections) * len(INJECTION_DEPTHS_PPM) * per_condition
            negatives = len(nulls) * per_condition
            positives_per_depth = len(injections) * per_condition
            balance = positives_per_depth / (positives_per_depth + negatives) if negatives else 0.0
            checks = {
                "quarters": len({w["quarter"] for w in subset}),
                "injection_windows": len(injections),
                "null_windows": len(nulls),
                "positives": positives,
                "negatives_null": negatives,
                "positives_per_depth": positives_per_depth,
                "prevalence_null_only": round(positives / (positives + negatives), 4),
                "per_depth_balance": round(balance, 4),
            }
            passed = (
                len(injections) >= FEASIBILITY_MINIMUMS["injection_windows"][split]
                and len(nulls) >= FEASIBILITY_MINIMUMS["null_windows"][split]
                and positives_per_depth >= FEASIBILITY_MINIMUMS["positives_per_depth_per_split"]
                and FEASIBILITY_MINIMUMS["per_depth_balance_range"][0]
                <= balance
                <= FEASIBILITY_MINIMUMS["per_depth_balance_range"][1]
            )
            checks["pass"] = bool(passed)
            ok = ok and passed
            rows[split] = checks
        report[label] = {"window_days": manifests[key]["window_days"], "pass": ok, "splits": rows}
    return report


def write_manifests(out_dir: Path, root: Path | None = None) -> dict[str, dict]:
    """Write the manifests as canonical JSON (no timestamps: byte-reproducible)."""
    manifests = build_manifests(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in manifests.items():
        (out_dir / name).write_text(
            json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )
    return manifests


def main() -> None:  # pragma: no cover - CLI glue
    parser = argparse.ArgumentParser(description="Freeze the Phase 11a split and window manifests.")
    parser.add_argument("--out", default=None, help="output directory")
    args = parser.parse_args()
    out_dir = (
        Path(args.out) if args.out else project_root() / "reports" / "phase11_generalization"
    )
    manifests = write_manifests(out_dir)
    report = feasibility_report(manifests)
    print(json.dumps({"written_to": str(out_dir), "feasibility": report}, indent=2))
    if not all(entry["pass"] for entry in report.values()):
        raise SystemExit("feasibility check failed")


if __name__ == "__main__":  # pragma: no cover
    main()
