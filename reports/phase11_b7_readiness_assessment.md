# Phase 11 B7 — Readiness Assessment (assessment only; B7 not executed)

Repository: `%USERPROFILE%\astronomy-ai`
Inputs read: `reports/phase11_stageB_design.md` (§5.3, §5.8 B7 row, §7), `reports/phase11_b5_readiness_decision.md`,
`reports/phase11_b6_mmd_decision.md`, current `research/` code and its focused tests.
Status: **not ready**. No campaign, trial generation, fitting, sealed-test access, protocol change,
readiness change, staging or commit occurred. This document adds no execution capability.

## 1. Prerequisite matrix

| # | Prerequisite | Status | Evidence |
|---|---|---|---|
| 1 | Real-data trial generator and its safety boundaries | **MISSING** | the only generator is synthetic: `phase11_b2.build_test_frame` assembles rows from `b2a.synthetic_window` arrays and stamps `source = "synthetic-fixture"`; the evaluator refuses anything else (`phase11_b3.py:214-217`), as does the fitter (`phase11_b1.py:149-153`) |
| 2 | Frozen denominator recomputation (76 nulls, 72 injections per depth per stratum, 5 test clusters) | **MISSING** | the literals exist only as prose (`phase11_b3.py:475`, `phase11_b5.py:48`); no code recomputes them. `phase11_v2.campaign_preconditions` verifies protocol/manifest/offset hashes and the tree, but not denominators. The protocol requires the recomputation "before any evaluation" (`reporting.denominator_derivation.consistency_requirement`) |
| 3 | Authenticated protocol and fitted-state contracts | **VERIFIED** | protocol pin `e1dc5cc9ed4e6e2dc4645a82efc4f7638fb0f3128248b9810c67ba339f32c154` with sidecar, header and invariant checks (`load_protocol_v21`); nine-key payload including `detector_thresholds`; `freeze_fitted_v21` refuses a payload without it before writing; `load_fitted_v21` re-verifies the JSON hash, model hash and protocol binding. Covered by `tests/test_phase11_b0_resolution.py`, `tests/test_phase11_b1.py`, `tests/test_phase11_b4.py` |
| 4 | G12 refusal/audit integrity | **VERIFIED, with a stated limitation** | records carry stage, gate, message, pinned protocol hash, deterministic configuration hash, campaign path, frozen fitted hash and timestamp; the audit directory must resolve outside the frozen tree; an unwritable audit surfaces as `GateError`. Covered by `tests/test_phase11_b3.py` (refusal fields, isolation, write failure) and `tests/test_phase11_b4.py` (fitted-hash plumbing, payload validation). **Limitation:** records are plain JSON with no hash chain or sidecar, so an edited historical record is not detectable |
| 5 | Clean-tree and commit requirements | **MISSING** | the tracked tree is dirty (three modified tracked files) and the new modules are untracked; HEAD is still `230c5ae8c26b87abd719c09548a23beab8f37222`. `require_clean_tree` (used by `phase11_b1.fit_synthetic` and `phase11_v2.campaign_preconditions`) refuses this state, so a real preflight would abort at provenance |
| 6 | Explicit external authorization | **MISSING** | no authorization document exists in `reports/`; the design requires one naming the operator, date and single-run condition (§5.8 B7 row and the "Sealed-test access" decision row). The B5 record states the same required approval and that no v2.4 readiness revision is proposed |

Readiness flags are unchanged and remain authoritative-by-absence: `campaign_ready = false`,
`execution_ready = false`, protocol status "PROPOSAL ONLY". `phase11_runner.execute_real` refuses
unconditionally, and `phase11_b5.assess_readiness` still records `external_readiness_not_granted`.

## 2. Design ambiguities that block a valid confirmatory run

These are not implementation gaps that B7 can paper over; each needs an explicit decision.

**A. The evaluator's synthetic-only source gate has no real-data counterpart.** `assert_test_trials`
requires `source == "synthetic-fixture"` and refuses anything else. The design never specifies the
source tag, schema or acceptance rule for a real campaign's test artifact, nor whether the B3
evaluator is meant to consume it at all. Generating real trials without deciding this would produce
an artifact the evaluator refuses by construction.

**B. The fitter's synthetic-only guard has no authorized real path.** B1's `assert_synthetic_frame`
refuses non-synthetic rows before feature extraction. The design's B4 decision row says the real fit
path is "code (B0 + B2a + B1) plus authorization to run it", but B1 as written cannot accept real
rows; which guard replaces the synthetic-source check, and under what marker, is unspecified.

**C. Denominator enforcement has no owner.** The protocol says "the runner recomputes these
denominators from the frozen inputs before any evaluation"; the design does not say whether the
check belongs to the generator, the evaluator, or a preflight, nor what artifact records it. Any
placement is a design decision, not an implementation detail.

**D. The confirmatory ceiling is already fixed by B6.** With the minimum meaningful difference
unset, the best attainable status is `descriptive_only`; a B7 run can never report superiority.
That is a deliberate scientific choice, not a defect — but an authorization that expects a
confirmatory superiority claim would be inconsistent with the frozen protocol.

**E. Readiness is external to the protocol.** The B5 record keeps both flags false and relies on an
authorization document instead. A B7 run therefore proceeds without any protocol-level readiness
assertion; the authorization document must carry that weight explicitly, or a v2.4 revision is
needed first.

**F. The real generator's inputs are frozen but unimplemented.** `split.json`,
`windows_primary.json`/`windows_sensitivity.json`, `offsets.json` and `experiment_config.json`
already define quarters, windows, role assignment, offset draws, depths and noise strata. A real
generator must consume those, not define new ones; the design does not name the module that will,
nor whether it mirrors B2's claim/marker protocol (it should, to keep one generation claim).

## 3. What is genuinely ready

- The protocol, offsets, five manifests and experiment config are hash-frozen and verified on every
  load, with no open fields.
- The fitted-state contract is complete, including the comparator table, and fails closed when the
  table is absent or the model file is corrupt.
- Access and generation markers are one-shot, cross-process and terminal on interruption; the
  evaluator claims access before its first read.
- The G12 trail is implemented, field-complete and isolated from the protected tree.
- The synthetic path (B0 → B2a → B1 → B2 → B3) runs end to end on fixtures with every gate green,
  which is what makes the remaining gaps enumerable rather than speculative.

## 4. Minimum sequence to close the blockers

1. Owner decision on ambiguity **A** and **B** (how real trials are tagged and which guarded fit
   path is authorized) — a design addition, then code, then review.
2. Owner decision on ambiguity **C** (where the denominator recomputation lives and what it records).
3. Commit the current source baseline and produce a clean tracked tree.
4. Write the B7 authorization document naming operator, date, single-run condition, the authorized
   scope (primary 5-day campaign; sensitivity reported separately) and the descriptive-only ceiling
   from **D**.
5. Run the campaign only under that authorization; the sealed-test read stays one-shot and ledged.

## 5. Verification performed for this assessment

| Check | Result |
|---|---|
| 21 protected artifacts | 21/21 byte-identical |
| `protocol_v2_3.json` | `e1dc5cc9…c154`; `campaign_ready = false`, `execution_ready = false` |
| campaign markers / trials / metrics in the repository | none |
| Git | HEAD `230c5ae8…`, 0 staged, no commits, `git diff --check` clean |
| files modified by this assessment | none except this report |

## 6. Verdict

**B7 is not ready to execute.** Four prerequisites are missing (real generator with its source-tag
decision, denominator enforcement, clean committed tree, authorization document), two are verified
(protocol/fitted contracts, G12), and five design ambiguities require owner decisions before any
code. No real-trial generation, fitting, sealed-test access, readiness change or B7 functionality was
implemented.
