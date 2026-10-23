"""Shared gate exception.

Kept in a leaf module so that the access state machine, the Phase 11 v1 gates and the
Phase 11 v2 gates all raise the *same* exception class without an import cycle.
"""

from __future__ import annotations


class GateError(RuntimeError):
    """Raised when a leakage, freeze-order or one-shot access gate is violated."""


__all__ = ["GateError"]
