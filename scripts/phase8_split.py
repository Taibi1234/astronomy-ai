"""Phase 8 — segment-level split assignment (single source of truth).

Reproduces the Phase 5 rule exactly: shuffle the sorted unique parent-segment IDs
with numpy's legacy RNG seeded at 42, then cut 50% / 25% / 25%. The Phase 5 script
used `np.random.seed(42); np.random.shuffle(...)`, which is equivalent to
`np.random.RandomState(42).shuffle(...)`.

Keeping this in one module means the feature file and the evaluation cannot
disagree about which window belongs to which split.
"""

import numpy as np

SPLIT_SEED = 42


def assign_splits(segment_ids):
    """Return an array of 'train' | 'val' | 'test' labels, one per window."""
    segment_ids = np.asarray(segment_ids)
    unique = np.unique(segment_ids)
    rng = np.random.RandomState(SPLIT_SEED)
    rng.shuffle(unique)

    n = len(unique)
    groups = {
        "train": set(unique[: n // 2].tolist()),
        "val": set(unique[n // 2 : 3 * n // 4].tolist()),
        "test": set(unique[3 * n // 4 :].tolist()),
    }
    out = []
    for raw_sid in segment_ids:
        sid = int(raw_sid)
        match = [name for name, members in groups.items() if sid in members]
        if len(match) != 1:
            raise ValueError(f"segment {sid} does not belong to exactly one split: {match}")
        out.append(match[0])
    return np.array(out), groups
