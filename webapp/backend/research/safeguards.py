"""Fail-closed write protection for Phase 11 command-line entry points.

The three legacy CLIs default to writing into ``reports/phase11_generalization`` and its
two historical smoke directories. Those directories hold frozen protocol inputs and the
preserved smoke/quarantine artifacts, so a defaulted ``--out`` would overwrite protected
evidence. Every CLI that writes must call :func:`assert_safe_output` first.

The guard is deliberately independent of the protocol machinery: it imports nothing from
``phase11`` or ``generalization``, so it cannot create an import cycle, and it can be
exercised entirely with temporary directories.
"""

from __future__ import annotations

from pathlib import Path

MANIFEST_DIRNAME = "phase11_generalization"
SMOKE_DIRNAME = "smoke"
QUARANTINE_DIRNAME = "smoke_invalid_scope_20261022"

PROTECTED_DIRECTORIES = (
    (MANIFEST_DIRNAME, "frozen Phase 11 inputs"),
    (SMOKE_DIRNAME, "historical smoke output"),
    (QUARANTINE_DIRNAME, "invalid-scope quarantine"),
)

FROZEN_ARTIFACT_NAMES = frozenset(
    {
        "protocol.json",
        "protocol.sha256",
        "offsets.json",
        "offsets.sha256",
        "split.json",
        "windows_primary.json",
        "windows_sensitivity.json",
        "null_library.json",
        "experiment_config.json",
        "protocol_v2.json",
        "protocol_v2.sha256",
        "protocol_v2_1.json",
        "protocol_v2_1.sha256",
        "protocol_v2_2.json",
        "protocol_v2_2.sha256",
        "protocol_v2_3.json",
        "protocol_v2_3.sha256",
        "fitted.json",
        "fitted.sha256",
        "model.pkl",
        "trials_fit.csv",
        "trials_test.csv",
        "metrics_test.json",
        "test_access.json",
        "test_generation.json",
    }
)


CAMPAIGN_STATE_NAMES = frozenset(
    {
        "fitted.json",
        "fitted.sha256",
        "model.pkl",
        "test_access.json",
        "test_generation.json",
        "metrics_test.json",
        "trials_fit.csv",
        "trials_test.csv",
    }
)


class SafeguardError(RuntimeError):
    """Raised when a write target could overwrite protected Phase 11 evidence."""


def manifest_dir(root: Path) -> Path:
    return root / "reports" / MANIFEST_DIRNAME


def protected_paths(root: Path) -> list[tuple[str, Path]]:
    base = manifest_dir(root)
    return [
        (label, base / name if name else base)
        for name, label in (
            ("", "frozen Phase 11 inputs"),
            (SMOKE_DIRNAME, "historical smoke output"),
            (QUARANTINE_DIRNAME, "invalid-scope quarantine"),
        )
    ]


def assert_not_protected_directory(target: Path, *, root: Path, purpose: str) -> Path:
    """Refuse only when the target *is* one of the three protected directories.

    This is the narrower check used by writers that legitimately regenerate their own
    outputs: re-writing the same fresh directory twice must keep working, while the
    protected evidence directories themselves stay untouchable.
    """
    resolved = Path(target).resolve()
    for label, path in protected_paths(root):
        if resolved == path.resolve():
            raise SafeguardError(
                f"{purpose}: refusing to write into the protected {label} directory "
                f"({path}); pass an explicit new --out directory"
            )
    return resolved


def assert_safe_output(target: Path, *, root: Path, purpose: str) -> Path:
    """Refuse to write into, or over, protected Phase 11 evidence.

    Two independent conditions trigger a refusal:

    1. the target resolves to one of the three protected directories; or
    2. the target already contains a protected artifact by name, which catches copies of
       a protected layout made anywhere on disk.

    Both are checked before any write, so a refusal leaves the target untouched.
    """
    resolved = assert_not_protected_directory(target, root=root, purpose=purpose)
    for name in sorted(FROZEN_ARTIFACT_NAMES):
        if (resolved / name).exists():
            raise SafeguardError(
                f"{purpose}: target {resolved} already contains the protected artifact "
                f"{name}; refusing to overwrite it"
            )
    return resolved


def assert_no_campaign_state(target: Path, *, purpose: str) -> Path:
    """Refuse a target that already holds fitted, access or trial artifacts.

    These names are never produced by the manifest or stage-0 writers, so refusing them
    keeps both writers repeatable in a fresh directory while catching a copied protected
    layout (which always contains ``fitted.json``/``model.pkl``/``trials_*.csv``).
    """
    resolved = Path(target).resolve()
    present = sorted(name for name in CAMPAIGN_STATE_NAMES if (resolved / name).exists())
    if present:
        raise SafeguardError(
            f"{purpose}: target {resolved} already holds campaign state {present}; "
            "refusing to write into a campaign or copied protected directory"
        )
    return resolved


__all__ = [
    "CAMPAIGN_STATE_NAMES",
    "FROZEN_ARTIFACT_NAMES",
    "MANIFEST_DIRNAME",
    "PROTECTED_DIRECTORIES",
    "QUARANTINE_DIRNAME",
    "SMOKE_DIRNAME",
    "SafeguardError",
    "assert_no_campaign_state",
    "assert_not_protected_directory",
    "assert_safe_output",
    "manifest_dir",
    "protected_paths",
]
