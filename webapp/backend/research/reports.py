"""Phase 10 report generator: plot data, figures, and Markdown from saved artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

UNIT_DEPTH = "injected depth (ppm)"
UNIT_FRACTION = "recovery fraction"


def plot_data_from_summary(summary: dict, trials) -> dict:
    controls = trials[(~trials["injected"]) & trials["valid"]]
    injected = trials[trials["injected"] & trials["valid"]]

    return {
        "recovery_by_depth": summary["recovery_by_depth_all_splits"],
        "recovery_by_depth_test": summary["recovery_by_depth_test_split"],
        "recovery_by_dataset_and_noise": summary["recovery_by_dataset_and_noise"],
        "controls": {
            "snr": [float(v) for v in controls["snr"]],
            "thresholds": {
                key: value["threshold_snr"] for key, value in summary["thresholds"].items()
            },
            "n": int(len(controls)),
            "n_test": int(summary["false_positive_rate"]["controls"]),
            "false_positives": int(summary["false_positive_rate"]["false_positives"]),
            "scope": (
                "S/N histogram uses all valid zero-depth controls (calibration + test); "
                "the false-positive rate uses test-split controls only"
            ),
        },
        "recovered_vs_injected": [
            {
                "requested_depth_ppm": float(row.requested_depth_ppm),
                "recovered_depth_ppm": float(row.depth_est_ppm),
                "recovered": bool(row.recovered),
                "dataset": row.dataset,
            }
            for row in injected.itertuples()
        ],
        "timing_errors_days": [float(v) for v in injected["timing_error_days"]],
        "timing_tolerance_days": summary["config"]["tolerance_days"],
        "benchmark": {
            name: {"f1": block.get("f1"), "n": block.get("n")}
            for name, block in summary["benchmark"].get("methods", {}).items()
        },
        "units": {
            "depth": UNIT_DEPTH,
            "fraction": UNIT_FRACTION,
            "timing": "absolute timing error (days)",
            "snr": "matched-filter S/N",
        },
    }


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def write_figures(  # noqa: PLR0915 - one block per figure
    plot_data: dict, out_dir: Path
) -> list[str]:
    written = []
    out_dir.mkdir(parents=True, exist_ok=True)

    series = plot_data["recovery_by_depth"]
    if series:
        depths = [row["requested_depth_ppm"] for row in series]
        frac = [row["fraction"] or 0.0 for row in series]
        lo = [max(0.0, row["fraction"] - (row["wilson_low"] or 0.0)) for row in series]
        hi = [max(0.0, (row["wilson_high"] or 0.0) - row["fraction"]) for row in series]
        fig, ax = plt.subplots(figsize=(6.4, 3.6))
        ax.errorbar(depths, frac, yerr=[lo, hi], marker="o", capsize=3, color="#2a6f97")
        for row in series:
            ax.annotate(
                f"{row['recovered']}/{row['trials']}",
                (row["requested_depth_ppm"], row["fraction"] or 0.0),
                textcoords="offset points",
                xytext=(0, 7),
                fontsize=7,
                ha="center",
            )
        ax.set_xlabel(UNIT_DEPTH)
        ax.set_ylabel(UNIT_FRACTION)
        ax.set_ylim(-0.05, 1.05)
        ax.set_title("Recovery vs injected depth (all splits, Wilson 95%)", fontsize=9)
        ax.grid(alpha=0.25)
        _save(fig, out_dir / "recovery_vs_depth.png")
        written.append("recovery_vs_depth.png")

    controls = plot_data["controls"]
    if controls["snr"]:
        fig, ax = plt.subplots(figsize=(6.4, 3.6))
        ax.hist(controls["snr"], bins=max(5, min(20, len(controls["snr"]))), color="#7187a0")
        for key, value in controls["thresholds"].items():
            ax.axvline(value, linestyle="--", linewidth=1, label=f"threshold {key}")
        ax.set_xlabel("matched-filter S/N (zero-depth controls)")
        ax.set_ylabel("trials")
        ax.set_title(
            f"Zero-depth control S/N (n={controls['n']}; "
            f"FPR on {controls['n_test']} test controls)",
            fontsize=8,
        )
        ax.legend(fontsize=6)
        ax.grid(alpha=0.25)
        _save(fig, out_dir / "control_snr.png")
        written.append("control_snr.png")

    points = plot_data["recovered_vs_injected"]
    if points:
        fig, ax = plt.subplots(figsize=(6.4, 3.6))
        xs = [p["requested_depth_ppm"] for p in points]
        ys = [p["recovered_depth_ppm"] for p in points]
        ax.scatter(xs, ys, s=12, alpha=0.6, color="#2a6f97")
        limit = max(*xs, *ys) * 1.1
        ax.plot([0, limit], [0, limit], "k--", linewidth=0.8, label="1:1")
        ax.set_xlabel(UNIT_DEPTH)
        ax.set_ylabel("recovered depth (ppm)")
        ax.set_title("Recovered vs injected depth (all injected trials)", fontsize=9)
        ax.legend(fontsize=7)
        ax.grid(alpha=0.25)
        _save(fig, out_dir / "recovered_vs_injected.png")
        written.append("recovered_vs_injected.png")

    errors = plot_data["timing_errors_days"]
    if errors:
        fig, ax = plt.subplots(figsize=(6.4, 3.6))
        ax.hist(errors, bins=max(5, min(20, len(errors))), color="#8c6d3f")
        ax.axvline(
            plot_data["timing_tolerance_days"],
            linestyle="--",
            linewidth=1,
            label=f"tolerance {plot_data['timing_tolerance_days']:.4f} d",
        )
        ax.set_xlabel("absolute timing error (days)")
        ax.set_ylabel("trials")
        ax.set_title("Transit-centre timing error (injected trials)", fontsize=9)
        ax.legend(fontsize=7)
        ax.grid(alpha=0.25)
        _save(fig, out_dir / "timing_error.png")
        written.append("timing_error.png")

    bench = plot_data["benchmark"]
    usable = {k: v["f1"] for k, v in bench.items() if v.get("f1") is not None}
    if usable:
        fig, ax = plt.subplots(figsize=(6.4, 3.6))
        ax.bar(list(usable), list(usable.values()), color="#4f7a8c")
        ax.set_ylabel("test F1")
        ax.set_ylim(0, 1.05)
        ax.set_title("Detection benchmark on the same grouped test chunks", fontsize=9)
        plt.xticks(rotation=15, fontsize=7)
        ax.grid(axis="y", alpha=0.25)
        _save(fig, out_dir / "benchmark_f1.png")
        written.append("benchmark_f1.png")

    return written


def _pct(value) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _num(value, digits: int = 3) -> str:
    return "unavailable" if value is None else f"{value:.{digits}f}"


def render_markdown(  # noqa: C901, PLR0912 - report layout
    summary: dict, plot_data: dict
) -> str:
    cfg = summary["config"]
    b = summary["benchmark"]
    p = summary["provenance"]
    counts = summary["counts"]

    lines = [
        "# Injection Recovery & Detection Benchmark",
        "",
        f"**Mode:** `{summary['mode']}` · **status:** {summary['status']} · "
        f"**runtime:** {summary['runtime_seconds']} s · **finished:** {summary['finished_at']}",
        "",
        "> Synthetic injections only. Recovery of simulated transits does **not** establish",
        "> real-planet detection performance.",
        "",
        "## Research question",
        "",
        "How successfully does a period-known, phase-folded matched filter recover injected",
        "Kepler-10 b transits of known depth, and how does it compare with the project's ML",
        "baselines on identical windows?",
        "",
        "## Data",
        "",
    ]
    for m in cfg["datasets"]:
        lines.append(
            f"- `{m}`: SHA-256 `{p['source_hashes'][m][:16]}…`, "
            f"{counts['chunks'][m]} contiguous chunks, split "
            f"{counts['splits'][m]['chunks']}"
        )
    lines += [
        "",
        "Time systems follow the project convention: BKJD = BJD_TDB − 2454833.0 (Kepler),",
        "TJD = BJD_TDB − 2457000.0 (TESS).",
        "",
        "## Transit model and injection",
        "",
        "- Ephemeris: P = 0.837491225 d, T0 = 2454964.575 BJD_TDB.",
        "- Geometry: a/R* = 3.4, i = 84.5°, quadratic limb darkening u = [0.30, 0.20].",
        "- Radius ratio: rp = sqrt(depth_ppm × 1e-6); injection formula "
        "`flux + median(flux) × (model − 1)` (the Phase 5 formula, reused).",
        "- Hidden phase offset per chunk: uniform in ±0.10 d; the same offset is reused across",
        "  depths and noise conditions for paired comparisons.",
        f"- Search grid: ±{cfg['search_half_days']} d in {cfg['search_step_days']} d steps.",
        f"- Timing tolerance: {cfg['tolerance_days']:.4f} d (half the 1.81 h transit duration).",
        "",
        "## Detector and thresholds",
        "",
        "- Folds each chunk at the published period, scans the phase offset, and computes a",
        "  matched-filter amplitude with the same batman template shape as the injection.",
        "- Detection threshold = 95th percentile of **train-split zero-depth controls** per",
        "  (dataset, noise condition). The detector never receives the injected depth or offset.",
        "",
        "| dataset \\| noise | threshold S/N | calibration controls | source |",
        "|---|---:|---:|---|",
    ]
    for key, value in summary["thresholds"].items():
        lines.append(
            f"| {key.replace('|', ' / ')} | {value['threshold_snr']:.2f} | "
            f"{value['n_calibration_controls']} | {value['source']} |"
        )

    lines += [
        "",
        "## Recovery by injected depth (all splits)",
        "",
        "| requested (ppm) | recovered | trials | fraction | Wilson 95% | "
        "median recovered depth (ppm) |",
        "|---:|---:|---:|---:|---|---:|",
    ]
    for row in plot_data["recovery_by_depth"]:
        ci = f"[{_pct(row['wilson_low'])}, {_pct(row['wilson_high'])}]"
        lines.append(
            f"| {row['requested_depth_ppm']:.0f} | {row['recovered']} | {row['trials']} | "
            f"{_pct(row['fraction'])} | {ci} | {_num(row['median_recovered_depth_ppm'], 1)} |"
        )

    lines += [
        "",
        "### Test-split only (locked evaluation)",
        "",
        "| requested (ppm) | recovered | trials | fraction | Wilson 95% |",
        "|---:|---:|---:|---:|---|",
    ]
    for row in plot_data["recovery_by_depth_test"]:
        ci = f"[{_pct(row['wilson_low'])}, {_pct(row['wilson_high'])}]"
        lines.append(
            f"| {row['requested_depth_ppm']:.0f} | {row['recovered']} | {row['trials']} | "
            f"{_pct(row['fraction'])} | {ci} |"
        )

    fpr = summary["false_positive_rate"]
    lines += [
        "",
        "## Zero-depth controls",
        "",
        f"- Controls used for the false-positive estimate: {fpr['controls']} "
        "(chunks not used for threshold calibration).",
        f"- False positives: {fpr['false_positives']} → rate {_pct(fpr['rate'])} "
        f"(Wilson [{_pct(fpr['wilson_low'])}, {_pct(fpr['wilson_high'])}]).",
        f"- Definition: {fpr['definition']}.",
        "",
        "## Recovery by dataset and noise condition",
        "",
        "| dataset | noise | recovered | trials | fraction | Wilson 95% |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in summary["recovery_by_dataset_and_noise"]:
        ci = f"[{_pct(row['wilson_low'])}, {_pct(row['wilson_high'])}]"
        lines.append(
            f"| {row['dataset']} | {row['noise_condition']} | {row['recovered']} | "
            f"{row['trials']} | {_pct(row['fraction'])} | {ci} |"
        )

    lines += [
        "",
        "## Detection benchmark",
        "",
        f"Status: **{b.get('status', 'unknown')}**"
        + (f" — {b.get('reason')}" if b.get("reason") else ""),
        "",
        "| split | windows | groups | positive | negative |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, s in b.get("splits", {}).items():
        lines.append(
            f"| {name} | {s['windows']} | {s['groups']} | {s['positive']} | {s['negative']} |"
        )

    lines += [
        "",
        "| method | n | prevalence | precision | recall | F1 | ROC-AUC | PR-AUC | no-skill F1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, block in b.get("methods", {}).items():
        lines.append(
            f"| {name} | {block.get('n')} | {_num(block.get('prevalence'))} | "
            f"{_num(block.get('precision'))} | {_num(block.get('recall'))} | "
            f"{_num(block.get('f1'))} | {_num(block.get('roc_auc'))} | "
            f"{_num(block.get('pr_auc'))} | "
            f"{_num(block.get('f1_no_skill_predict_all_positive'))} |"
        )

    prevalence = next(
        (
            m.get("prevalence")
            for m in b.get("methods", {}).values()
            if m.get("prevalence") is not None
        ),
        None,
    )
    no_skill = next(
        (
            m.get("f1_no_skill_predict_all_positive")
            for m in b.get("methods", {}).values()
            if m.get("f1_no_skill_predict_all_positive") is not None
        ),
        None,
    )
    if prevalence is not None and no_skill is not None:
        lines += [
            "",
            f"Test-set positive prevalence is **{prevalence:.3f}**; the **no-skill F1**",
            "column is the score from predicting positive for every window",
            f"(`2p/(1+p) = {no_skill:.3f}`). A method at or below that value has",
            "demonstrated no skill. Under this class imbalance F1 alone is not",
            "interpretable, so ROC-AUC and per-depth recovery are reported alongside it.",
        ]

    if b.get("per_depth_test"):
        lines += [
            "",
            "### Per-depth behaviour on the test split",
            "",
            "| requested (ppm) | trials | physics recovered | logistic detected |",
            "|---:|---:|---:|---:|",
        ]
        for row in b["per_depth_test"]:
            lines.append(
                f"| {row['requested_depth_ppm']:.0f} | {row['trials']} | "
                f"{row['physics_recovered']} | {row['logistic_detected']} |"
            )

    lines += ["", "## Figures", ""]
    for name in (
        "recovery_vs_depth.png",
        "control_snr.png",
        "recovered_vs_injected.png",
        "timing_error.png",
        "benchmark_f1.png",
    ):
        lines.append(f"- `figures/{name}`")

    exclusions = summary.get("excluded_trials") or []
    lines += ["", "## Failed and excluded trials", ""]
    lines.append(f"- Invalid trials: {counts['trials_invalid']}")
    for row in exclusions:
        lines.append(f"  - {row['count']} × {row['reason']}")
    if not exclusions:
        lines.append("- No trials were excluded.")

    lines += [
        "",
        "## Reproducibility",
        "",
        f"- Command: `{p['command']}`",
        f"- Seed: {p['seed']} · Python {p['python']} · git `{p['git_commit']}`",
        f"- Packages: numpy {p['packages']['numpy']}, pandas {p['packages']['pandas']}, "
        f"scikit-learn {p['packages']['scikit-learn']}, batman {p['packages']['batman']}",
        f"- Started {summary['started_at']} · finished {summary['finished_at']} · "
        f"{summary['runtime_seconds']} s",
        "- Artifacts: `config.json`, `trial_results.csv`, `summary.json`, `plot_data.json`, "
        "`provenance.json`, `figures/`.",
        "",
        "## Limitations",
        "",
    ]
    for item in summary["limitations"]:
        lines.append(f"- {item}")
    lines += [
        "- Wilson intervals describe this experiment's trials, not all future observations.",
        "- With 3–4 contiguous chunks per dataset, per-dataset comparisons are exploratory.",
        "",
        "## Scientific statement",
        "",
        "Synthetic injection recovery measures pipeline sensitivity to simulated signals. It is",
        "not a planet detection, not a discovery claim, and not evidence of "
        "real-world performance.",
    ]
    return "\n".join(lines) + "\n"


def write_markdown(summary: dict, plot_data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(summary, plot_data), encoding="utf-8")


def regenerate_from_artifacts(artifacts_dir: Path) -> dict:
    """Rebuild report.md and figures from saved summary/plot artifacts only."""
    summary = json.loads((artifacts_dir / "summary.json").read_text(encoding="utf-8"))
    trials = pd.read_csv(artifacts_dir / "trial_results.csv")
    # Rebuild derived plot data from the primary artifacts rather than trusting a
    # previously written plot_data.json, so a generator change is picked up.
    plot_data = plot_data_from_summary(summary, trials)
    (artifacts_dir / "plot_data.json").write_text(
        json.dumps(plot_data, indent=2) + "\n", encoding="utf-8"
    )
    write_figures(plot_data, artifacts_dir / "figures")
    write_markdown(summary, plot_data, artifacts_dir / "recovery_report.md")
    return summary
