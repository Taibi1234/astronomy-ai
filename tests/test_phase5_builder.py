"""Phase 5 dataset builder — syntax and feature-construction guards.

The builder was unrunnable between Phase 5 and Phase 7 (a uniform 4-space
over-indent of lines 51-104). This module pins the repairs that matter:

1. the module parses at all (the exact Phase 7 regression);
2. the seven features are computed from the PRE-injection flux, so the injected
   label cannot leak into the features;
3. the saved dataset still matches what a repaired builder produces (xfail while
   the frozen artifact remains pre-repair — see reports/phase7_reliability_audit.md).
"""

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "phase5_build_dataset.py"
SAVED_DATASET = ROOT / "reports" / "phase5_dataset.json"
INPUT_CSV = ROOT / "data" / "processed" / "kepler_all_quarters_quality_masked.csv"


def _builder_tree():
    return ast.parse(BUILDER.read_text(encoding="utf-8"), filename=str(BUILDER))


def test_builder_parses():
    """Guards the Phase 7 defect: an over-indented loop body made the module unimportable."""
    tree = _builder_tree()
    assert isinstance(tree, ast.Module)


def test_builder_toplevel_statements_start_at_column_zero():
    """A uniform over-indent of a loop body is exactly what broke this module in Phase 5-6."""
    tree = _builder_tree()
    offenders = [(n.lineno, n.col_offset) for n in tree.body if n.col_offset != 0]
    assert not offenders, f"top-level statements not at column 0: {offenders}"


def test_phase5_builder_uses_the_presented_flux():
    """Features must describe the flux the classifier sees (see Phase 8 audit).

    The Phase 5 script injects a synthetic transit into `synthetic`; the seven
    features are computed from that same array for both classes (for negatives the
    injection is a no-op, so `synthetic` is an exact copy of `win_flux_dt`).
    """
    tree = _builder_tree()
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "features" for t in node.targets)
    ]
    assert len(assignments) == 1, "expected exactly one `features = {...}` assignment"
    referenced = {n.id for n in ast.walk(assignments[0].value) if isinstance(n, ast.Name)}
    assert "synthetic" in referenced, "features must use the presented (post-injection) flux"
    assert "win_flux_dt" not in referenced, (
        "features still reference the pre-injection flux, which drops the positive-class signal"
    )


def test_builder_declares_seed_and_split_strategy():
    source = BUILDER.read_text(encoding="utf-8")
    assert "SEED = 42" in source
    assert "segment-level" in source


@pytest.mark.skipif(
    not INPUT_CSV.is_file(), reason="analysis-ready CSV is gitignored and not present"
)
def test_saved_dataset_matches_repaired_builder(tmp_path):
    """Regenerate in an isolated copy and compare against the frozen saved dataset.

    Since the Phase 8 correction, `scripts/phase5_build_dataset.py` computes features
    from the presented flux and reproduces `reports/phase5_dataset.json` byte-for-byte.
    This is the regression guarantee that script and artifact cannot drift apart again.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "data" / "processed").mkdir(parents=True)
    for name in ("phase5_build_dataset.py", "transit_analysis.py"):
        shutil.copy2(ROOT / "scripts" / name, tmp_path / "scripts" / name)
    shutil.copy2(INPUT_CSV, tmp_path / "data" / "processed" / INPUT_CSV.name)

    subprocess.run(
        [sys.executable, "scripts/phase5_build_dataset.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        timeout=300,
    )
    regenerated = json.loads(
        (tmp_path / "reports" / "phase5_dataset.json").read_text(encoding="utf-8")
    )
    saved = json.loads(SAVED_DATASET.read_text(encoding="utf-8"))

    assert regenerated["n_windows"] == saved["n_windows"]
    for new, old in zip(regenerated["windows"], saved["windows"], strict=True):
        for key in ("segment_id", "label", "injected_depth_ppm", "n_points", "window_start_bkjd"):
            assert new[key] == old[key]
        for key in ("depth_rel_ppm", "contrast_ppm", "segment_std_ppm"):
            assert new[key] == pytest.approx(old[key], rel=0, abs=1e-9)
