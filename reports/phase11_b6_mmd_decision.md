# Phase 11 Stage B6 — MMD Decision Record

Repository: `%USERPROFILE%\astronomy-ai`
Design authority: `reports/phase11_stageB_design.md` §5.8 (B6 row), §5.8 "B2: Minimum meaningful
difference unset" decision row, protocol decision `D1_minimum_meaningful_difference`
Decision: **the minimum meaningful difference stays unset; conclusions remain descriptive-only.**
Nothing is staged, committed or pushed, and readiness flags are unchanged.

## 1. What "MMD" means here — and the ambiguity in the request

In this repository **MMD is the minimum meaningful difference** — the practical-effect threshold
that would make a recall difference scientifically meaningful. It is protocol decision
`D1_minimum_meaningful_difference`, and v2.3 records it as `value: null`, "explicitly unset by
owner decision". `phase11_v2.MINIMUM_MEANINGFUL_DIFFERENCE` is `None`, and `paired_comparison`
refuses any caller-supplied override.

The requested kernel, bandwidth, sampling/permutation procedure and diagnostic seed do **not
exist anywhere in the frozen specification**. Searches over `reports/phase11_stageB_design.md`,
`protocol_v2_3.json` and `research/phase11_v2.py` return no occurrence of "kernel", "bandwidth",
"permutation", "maximum mean", "mean discrepancy", "two-sample" or any kernel test. MMD here is a
decision threshold, not a maximum-mean-discrepancy statistic, and inventing a kernel diagnostic
with an invented bandwidth and permutation seed would be exactly the kind of unspecified
scientific parameter the instructions forbid.

**B6 was therefore implemented as its design-specified branch** — "explicit value **or a recorded
decision to stay descriptive-only**" — and no MMD diagnostic was written. If a kernel MMD is
genuinely wanted as a new statistic, it needs its own design (kernel choice, bandwidth rule,
permutation count, seed, interpretation) and a protocol revision; it cannot be inferred from the
artifacts that exist.

## 2. Decision

| Item | Value |
|---|---|
| decision kind | `mmd_stays_unset_descriptive_only` |
| minimum meaningful difference | **unset** (`null`, decision D1) |
| reachable comparison statuses | `descriptive_only` or `inconclusive` |
| practical-superiority claim | prohibited (`practical_superiority_claim` is hard `False`) |
| override by caller | refused (`GateError`) |
| effect on FPR/recall gates | none: B6 only reads state and probes the existing enforcement |
| authorizes execution | **false** |

To change it, three things are required, recorded in the decision: an explicit owner decision
naming the substantive difference that matters; a protocol revision carrying that value, with its
sidecar and an independent review; and a repin of the implementation to the revised hash. A
one-off value must never be injected through code or a caller argument.

## 3. Implementation

`phase11_b6.assess_mmd_decision(manifest_dir, repo_root)` returns the decision record and refuses
to produce one when the state disagrees with the decision:

| Check | What it proves |
|---|---|
| `protocol_decision_D1` | the frozen protocol's D1 value is null and its status declares it unset; a protocol that starts carrying a value is refused ("B6 does not adopt a value") |
| `code_constant` | `phase11_v2.MINIMUM_MEANINGFUL_DIFFERENCE` is `None`; a non-null constant is refused |
| `enforcement` | through the public path: `paired_comparison(mmd=0.1)` is refused; a clean three-cluster comparison reports `descriptive_only` (never `superior`); `combine_confirmatory` cannot upgrade it and reports `practical_superiority_claim: false`; the reported `mmd` is null |

The record also carries a `diagnostic` field stating that no MMD diagnostic is specified, so the
absence is documented in the artifact rather than left implicit.

## 4. Files

| File | Change | SHA-256 |
|---|---|---|
| `webapp/backend/research/phase11_b6.py` | decision record + fail-closed checks (160 lines) | `e64b07c63a9fa2dde719cbc69904086c3234b025aad1b5df12ed9e0d91a69509` |
| `webapp/backend/tests/test_phase11_b6.py` | 14 focused tests (194 lines) | `72f7ecb371b44102c5920ea50ae7eafcfd33fbcdf7d9ed6b48fb29a519acc147` |
| `reports/phase11_b6_mmd_decision.md` | this record | see §5 |

No protocol, manifest, sidecar, fitted artifact, runner or readiness flag was modified.

## 5. Verification

| Command | Result |
|---|---|
| `pytest tests/test_phase11_b6.py -q` | 14 passed (5.0 s) |
| `pytest` on 6 directly related files (B5, B4, v2 stage-2, v2 review, Stage B readiness, protocol repin) | 145 passed (31.4 s) |
| `ruff check` / `ruff format --check` on both changed Python files | clean |
| 21 protected artifacts | 21/21 byte-identical |
| `protocol_v2_3.json` | `e1dc5cc9…c154`; `campaign_ready = false`, `execution_ready = false` |
| stray trials, markers or campaign artifacts | none |
| Git | HEAD `230c5ae8…`, 0 staged, no commits, `git diff --check` clean |

## 6. Remaining blocker (for the owner, not for B6)

A kernel-based two-sample MMD diagnostic is **unspecified**: no kernel, bandwidth rule,
permutation scheme or seed exists in the frozen design or protocol. If that statistic is wanted,
it requires a new design section and a protocol revision before any code. B7 (the real-campaign
authorization) remains unimplemented, as instructed.
