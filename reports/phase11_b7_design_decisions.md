# Phase 11 B7 — Design Decision Record

Repository: `%USERPROFILE%\astronomy-ai`
Authority: `reports/phase11_generalization/protocol_v2_3.json` (`e1dc5cc9…c154`, flags false,
status "PROPOSAL ONLY"), `reports/phase11_stageB_design.md`, `reports/phase11_b7_readiness_assessment.md`,
`reports/phase11_b5_readiness_decision.md`, `reports/phase11_b6_mmd_decision.md`.
Status: **design decisions only**. No code, protocol, manifest, fitted artifact or readiness flag was
changed, and no trial was generated or read. This record grants no authority.

## D1 — Source contract for real generated trials

**Decision.** Real campaign trials carry a distinct provenance tag, `real-campaign-v2`, in the
row field `source` and in the generation-marker payload field `source`, together with a
`campaign_id` (the authorization document's identifier, D5). The synthetic tag
`synthetic-fixture` is unchanged, and every existing synthetic guard keeps its exact bytes and
behaviour.

Acceptance is additive and authorization-gated, never a relaxation: the evaluator accepts a tag
only from an allow-list selected by an explicit authorized mode, and only when the campaign
directory carries a valid authorization record whose `campaign_id` matches the generation marker
and the row tag. A synthetic run cannot reach the real tag, and a real run cannot reach the
synthetic tag.

**Rationale.** The protocol defines no `source` field and no provenance tag (`data_roles` covers
roles, not tagging), so the tag is a code-level provenance contract, not a scientific parameter.
The real tag cannot be inferred from the synthetic one.

**Requirement.** Code change plus independent review under B7 authorization. No protocol revision,
unless the owner prefers the tag to be protocol-defined — that would be a v2.4 revision.

## D2 — Reuse of the frozen fitted state for real evaluation

**Decision. Reuse is prohibited.** A real campaign fits its own model (and its own comparator
threshold table) on the real train+val quarters and freezes that state before any test generation
or read. The existing synthetic fitted artifacts — including the B1 golden fixture — must never be
used to score real trials.

**Rationale.** Protocol `unresolved` U5: "reuse of the historical v1 fitted artifact for any v2
purpose is prohibited; a v2 campaign must fit its own model and record its own provenance". The B1
artifact was fitted on synthetic fixtures, so scoring real test trialswith it would answer a
different question and violate `data_roles.model_fitting`.

**Consequences.** The real path needs a guarded *fit* entry point (real fit rows in, same nine-key
payload out) in addition to a real generator; it must never fit on test rows, and the fitted state
must exist, hashed, before the generation claim. No fitting may occur inside evaluation.

**Requirement.** Code plus review; owner authorization to fit on scientific data (design decision
row B4). No protocol revision.

## D3 — Where denominator recomputation occurs and how counts are recorded

**Decision.** Two mandatory checks against the same frozen derivation:

1. **Generator, fail-fast.** Before `claim_generation`, the real generator recomputes the expected
   denominators from the hash-verified frozen inputs — 38 test null slots × 2 offset draws × 2
   noise conditions = 152 pooled nulls (76 per stratum); 36 injection slots × 5 depths × 2 offset
   draws × 2 noise conditions = 720 injections (360 per stratum, 72 per depth per stratum); and 5
   test quarters — and aborts on any mismatch.
2. **Evaluator, authoritative.** After the access claim and the hash-verified read, and before any
   scoring, the evaluator recomputes the same expectations and compares them with the artifact's
   observed counts. Any mismatch is a refusal; it never becomes a substitute denominator, a pool,
   a reweight or a relaxed target.

**Recording.** Expected and observed counts are written to (a) the generation marker payload
(`expected_denominators`, `observed_denominators`), (b) the `metrics_test.json` `denominators`
block, (c) B3's G12 refusal record when the check fails, and (d) the run provenance captured at
preflight. The protocol's `insufficient_data` minima remain the per-stratum gates; the campaign
literals are the campaign-level identity check.

**Requirement.** Code plus review. No protocol revision; the protocol already requires the
recomputation "before any evaluation".

## D4 — Minimum meaningful difference

**Decision.** MMD stays **unset** (`null`, decision D1). Practical-superiority claims remain
prohibited, `practical_superiority_claim` stays hard `False`, a caller-supplied value is refused,
and the best attainable status for any B7 comparison is `descriptive_only` (or `inconclusive`).

**Rationale.** B6 decision record; protocol `approval_decisions.D1` and `unresolved` U1. A B7
authorization that expects a confirmatory superiority claim would contradict the frozen protocol.

**Requirement.** None now. Setting a value later requires an owner decision, a protocol revision
with sidecar, an independent review and a repin.

## D5 — Required content of the external authorization document

**Decision.** Before any real trial is generated, a single authorization document must exist,
outside the frozen manifest tree, hash-recorded in the campaign's generation marker, metrics and
provenance. It must state:

| Field | Requirement |
|---|---|
| Identity | named operator (person or role) and the approving owner, with the approval reference |
| Scope | primary 5-day campaign on the frozen test quarters; the 3-day sensitivity run is separate and non-confirmatory; the TESS sector is excluded and descriptive only |
| Date | issuance date/time in UTC, plus an explicit single-run window |
| Single-run condition | exactly one generation claim and one access claim; interruption is terminal; no re-generation, re-reading or remediation by software |
| Bindings | protocol hash `e1dc5cc9…c154`, the five manifest hashes, the offsets hash, the frozen fitted-state hash, the source tag from D1, and the clean-tree commit |
| Acknowledgement | descriptive-only ceiling (D4), the five-cluster limitation, and that the achieved false-positive rate is never described as achieving 5 percent |

**Requirement.** Owner action. The document is the sole authority that replaces the absent
protocol readiness flags (B5 external-readiness decision).

## D6 — How the real generator inherits B2's protections

**Decision.** Inherit by reuse, not by copying: the real generator is the same code path with the
row source and the window/offset inputs parameterized, so the following are byte-identical in
behaviour and covered by the same tests:

| Protection | Inherited form |
|---|---|
| Isolation | `resolve_campaign_dir`: frozen-tree, protected-directory and file-collision refusal, plus re-validation after creation and before every write (TOCTOU narrowing) |
| Precondition | the frozen fitted state must exist and load under the pin before the generation claim |
| Claim / marker | `claim_generation` → write → `complete_marker` with `trials_rows` and `trials_sha256`; absent→started→completed only; interruption terminal; no marker creation if any marker exists |
| Provenance | `capture_provenance` with the same five manifest hashes, offsets hash, protocol pin, repository commit and dirty state, extended with the authorization `campaign_id` and the D3 counts |
| Integrity on read | `verify_generated_trials` recomputes the file hash, then `load_authorized_trials` re-checks the row count; the evaluator claims access before the first read |
| Manifest authority | test quarters and window slots come from the hash-verified `split.json` / `windows_primary.json`; offsets and injection draws come from `offsets.json` and `experiment_config.json`; no new draws are invented |

**Requirement.** Code plus review. No protocol or manifest change.

## Assumptions

1. The real campaign fits on the 10 train+val quarters and evaluates on the 5 test quarters
   declared in `split.json`; the primary window is 5 days, the 3-day run is reported separately.
2. `trials_test.csv` keeps the B2 column schema (including `delta_true_days` and `delta_est_days`),
   so `load_authorized_trials` and the timing-qualified recovery rule apply unchanged.
3. The two marker filenames are unchanged; only their payloads gain fields.
4. The authorization document is out-of-band but its hash and `campaign_id` are recorded in the
   campaign artifacts, so provenance remains self-contained.

## Unresolved questions (owner or protocol decisions, not implementable here)

1. **Tag in protocol or in code?** D1 records the tag as code-level provenance. If the owner wants
   it frozen in the protocol, a v2.4 revision (sidecar, review, repin) is required first.
2. **Real fit guard.** D2 authorizes a real fit entry point, but the design never specifies which
   guard replaces B1's synthetic-source check; that guard must be named and reviewed before code.
3. **Authorization identifier.** Whether a document reference (path + hash) is acceptable, or a
   signed artifact is required, is an owner decision; D5 assumes the former.
4. **Readiness representation.** With both flags false and readiness external (B5), the
   authorization document carries the whole burden; if the owner prefers protocol-level readiness,
   a v2.4 revision replaces D5's authority basis.

## What remains blocked

B7 cannot run: there is no real generator, no authorized real fit path, no denominator enforcement,
no clean committed tree and no authorization document. Decisions D1–D6 remove the design ambiguity;
they do not create capability or authority.
