"""The single one-shot test-access state machine for Phase 11.

Both the legacy v1 evaluator and the v2 preflight/freeze path use this module, so there is
exactly one definition of "claimed", "completed" and "invalid".

State machine
-------------
``absent -> started -> completed``

* ``started`` is created with ``O_CREAT|O_EXCL``, so a second process racing for the same
  marker loses and is refused. Atomicity is filesystem-level, not thread-level.
* ``completed`` is reached only from ``started`` by an atomic replace that carries a nonce;
  if another process replaced the file first, the loser fails closed.
* Nothing in this module deletes, truncates or resets a marker. An interrupted attempt
  leaves ``started`` on disk, which is terminal evidence: every later attempt is refused.
* A marker that exists but cannot be parsed, or whose status is not one of the two legal
  states, reads as ``invalid`` and blocks execution exactly like a completed marker.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .errors import GateError

MARKER_GENERATION = "test_generation.json"
MARKER_ACCESS = "test_access.json"
MARKERS = (MARKER_GENERATION, MARKER_ACCESS)
MARKER_STATES = ("started", "completed")
MARKER_SCHEMA_VERSION = 2


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def marker_path(out_dir: Path, name: str) -> Path:
    if name not in MARKERS:
        raise GateError(f"unknown marker: {name!r}")
    return Path(out_dir) / name


def marker_state(out_dir: Path, name: str) -> str | None:
    """Return None, 'started', 'completed' or 'invalid' (present but unusable)."""
    path = marker_path(out_dir, name)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "invalid"
    status = payload.get("status") if isinstance(payload, dict) else None
    return status if status in MARKER_STATES else "invalid"


def assert_no_markers(out_dir: Path) -> None:
    """Refuse if any test-access marker exists, in any state."""
    for name in MARKERS:
        state = marker_state(out_dir, name)
        if state is not None:
            raise GateError(
                f"{name} already exists in state {state!r}; markers are one-way and are "
                "never reset, deleted or reused by software"
            )


def _write_exclusive(path: Path, payload: dict) -> None:
    data = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(descriptor, data)
    finally:
        os.close(descriptor)


def _replace_atomically(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes((json.dumps(payload, indent=2) + "\n").encode("utf-8"))
    os.replace(temporary, path)


def begin_marker(out_dir: Path, name: str, payload: dict) -> Path:
    """Create a marker in state 'started' exactly once. Fail closed on any retry."""
    path = marker_path(out_dir, name)
    if path.exists():
        state = marker_state(out_dir, name) or "unreadable"
        raise GateError(
            f"{name} already exists in state {state!r}; an interrupted run is terminal "
            "evidence and must not be retried or reset by software"
        )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {
        **payload,
        "schema_version": MARKER_SCHEMA_VERSION,
        "marker": name,
        "status": "started",
        "started_at": _utc_now(),
    }
    try:
        _write_exclusive(path, record)
    except FileExistsError as exc:
        raise GateError(
            f"{name} was created concurrently by another process; failing closed"
        ) from exc
    return path


def complete_marker(out_dir: Path, name: str, extra: dict | None = None) -> dict:
    """The only permitted transition: started -> completed, written atomically.

    Completion carries a nonce and is re-read after the replace. If another process
    completed the marker first, our nonce is absent and this call fails closed.
    """
    path = marker_path(out_dir, name)
    state = marker_state(out_dir, name)
    if state is None:
        raise GateError(f"{name} does not exist; it cannot be completed")
    if state != "started":
        raise GateError(f"{name} is in state {state!r}; only started -> completed is allowed")
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(extra or {})
    record["status"] = "completed"
    record["completed_at"] = _utc_now()
    nonce = os.urandom(16).hex()
    record["completion_nonce"] = nonce
    try:
        _replace_atomically(path, record)
    except OSError as exc:
        raise GateError(f"{name} completion could not be committed: {exc}") from exc
    committed = json.loads(path.read_text(encoding="utf-8"))
    if committed.get("completion_nonce") != nonce:
        raise GateError(f"{name} completion lost a race to another process; failing closed")
    return record


def claim_access(out_dir: Path, payload: dict) -> Path:
    """Claim evaluation rights.

    Refused when an access marker exists in any state, and refused when a generation
    marker is present but not ``completed`` (an unfinished generation is not evaluable).
    """
    state = marker_state(out_dir, MARKER_ACCESS)
    if state is not None:
        raise GateError(
            f"{MARKER_ACCESS} already exists in state {state!r}; the access claim is "
            "one-shot and is never reset by software"
        )
    generation = marker_state(out_dir, MARKER_GENERATION)
    if generation not in (None, "completed"):
        raise GateError(
            f"{MARKER_GENERATION} is in state {generation!r}; test access requires a "
            "completed generation claim"
        )
    return begin_marker(out_dir, MARKER_ACCESS, payload)


def claim_generation(out_dir: Path, payload: dict) -> Path:
    """Claim the exclusive right to generate test trials."""
    for name in MARKERS:
        state = marker_state(out_dir, name)
        if state is not None:
            raise GateError(
                f"{name} already exists in state {state!r}; test-trial generation is "
                "refused after any access claim"
            )
    return begin_marker(out_dir, MARKER_GENERATION, payload)


__all__ = [
    "MARKERS",
    "MARKER_ACCESS",
    "MARKER_GENERATION",
    "MARKER_SCHEMA_VERSION",
    "MARKER_STATES",
    "assert_no_markers",
    "begin_marker",
    "claim_access",
    "claim_generation",
    "complete_marker",
    "marker_path",
    "marker_state",
]
