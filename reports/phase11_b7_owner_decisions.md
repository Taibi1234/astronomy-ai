# Phase 11 B7 — Owner Decision Brief

Repository: `%USERPROFILE%\astronomy-ai`
Inputs: `reports/phase11_b7_design_decisions.md`, `reports/phase11_b7_readiness_assessment.md`,
`reports/phase11_stageB_design.md`, `reports/phase11_generalization/protocol_v2_3.json`
(`e1dc5cc9…c154`, `campaign_ready = false`, `execution_ready = false`, status "PROPOSAL ONLY").
Status: **decision brief only**. It creates no authority, approves nothing, and changes no code,
protocol, manifest, fitted artifact or readiness flag. The recommendations below are technical, not
authorizations.

Four decisions remain open. Each needs a named human owner; the implementer may recommend but must
not approve.

---

## OD-1 — Real-trial source contract: protocol v2.4, or reviewed code-level extension?

**Question.** The evaluator currently refuses any trial whose `source` is not `synthetic-fixture`
(`phase11_b3.py:214-217`). Real trials need a distinct, authenticated tag. The protocol defines no
`source` field (`data_roles` covers roles only), so the tag can live in code or in a revision.

**Alternatives.**
- **(a) Protocol v2.4.** New artifact + sidecar + predecessor binding, the tag and acceptance rule
  frozen in the protocol, independent review, repin, and a re-baseline of the 21 protected
  artifacts. Highest immutability; slowest path; likely also settles OD-3 in the same revision.
- **(b) Reviewed code-level extension.** A tag (`real-campaign-v2`) plus `campaign_id` in rows and
  in the generation marker; the evaluator accepts tags only from an authorization-gated allow-list,
  with the contract documented in the decision record and covered by tests. Synthetic guards stay
  byte-identical.

**Consequences.** (a) makes the contract tamper-evident at the protocol level but adds a full
revision cycle before any generation, and forces every downstream check (B0, B5, B6) to be re-run
against a new hash. (b) keeps the pin stable and ships faster, but the tag's legitimacy is evidenced
by code plus review plus the marker payload rather than by the frozen protocol — a weaker
immutability story, mitigated by recording the contract in artifacts.

**Technical recommendation.** (b) for this campaign, with mandatory independent review of the
evaluator/generator diff; escalate to (a) if the owner wants protocol-level immutability or if OD-3
is decided in favour of a revision.

**Who must approve.** Repository owner / scientific lead (scope: which tags are legitimate for a
real run), plus an independent reviewer for the code change. **Not approved here.**

---

## OD-2 — Exact acceptable form of external authorization

**Question.** With readiness external (OD-3), the authorization document is the sole authority for a
real run. What form is acceptable?

**Required content** (from B7 decision D5): named approver and named operator; scope (5-day primary,
3-day sensitivity separate and non-confirmatory, TESS excluded); UTC issuance date and single-run
window; the single-run condition (exactly one generation claim and one access claim, interruption
terminal, no software remediation); bindings (protocol pin `e1dc5cc9…c154`, the five manifest
hashes, the offsets hash, the frozen fitted-state hash, the source tag from OD-1, and the clean-tree
commit); explicit acknowledgement of the descriptive-only ceiling, the five-cluster limitation and
that the achieved FPR is never described as achieving 5 percent.

**Alternatives.**
- **(a) Hashed document.** A file outside the frozen tree with a SHA-256 sidecar; the digest and a
  `campaign_id` are recorded in the generation marker, `metrics_test.json` and preflight provenance.
- **(b) Cryptographically signed document** (e.g. minisign). Stronger non-repudiation, but no verifier
  exists in this repository and it adds a tooling dependency.
- **(c) External ticket reference only** (issue ID, no hashed document). Cheapest, but the bindings
  above cannot be carried, so it is insufficient.

**Consequences.** (a) is verifiable with existing tooling (`sha256sum`) and fits current marker
payloads; the document is only as durable as the repository's storage of it. (b) buys
non-repudiation at the cost of new machinery and a new failure mode. (c) would leave the run record
unbound to any frozen identity.

**Technical recommendation.** (a), with the approval reference quoted inside the document.

**Who must approve.** The repository owner / principal investigator, in writing, naming themselves
as approver. A delegate may countersign but not substitute. **Not approved here.**

---

## OD-3 — Readiness: remain an external B5 decision, or move into a protocol revision?

**Question.** `campaign_ready` and `execution_ready` are `false`, and the protocol text still says
"PROPOSAL ONLY" while its `execution_ready_reason` predates the B0–B4 hardening. B5 decided readiness
is external. Does that stand for the real campaign?

**Alternatives.**
- **(a) Keep readiness external (status quo).** Flags stay false; the OD-2 authorization document is
  authoritative; every run artifact must carry the documentation-trap note.
- **(b) Protocol v2.4 revision** that supersedes the proposal status and (optionally) sets readiness
  after review. Strongest assurance, but requires a new artifact, sidecar, review, repin, and
  re-verification of all downstream gates; it also merges "authorized" with "ready", which B5
  deliberately separated.
- **(c) Hybrid:** v2.4 adds a readiness *reference* field while flags stay false — the cost of a
  revision with none of the authority.

**Consequences.** (a) has zero protocol churn and is already documented (B5 record), at the price of
a stale text that future operators must be told to ignore. (b) removes that trap permanently but
makes the protocol carry an authorization decision, weakening the separation between scientific
state and human authority. (c) is not worth its cost.

**Technical recommendation.** (a) for this campaign; revisit (b) if a second campaign is authorized,
where the revision cost is amortized. Whichever is chosen, the OD-2 document must be referenced from
every run artifact.

**Who must approve.** Owner. A protocol revision additionally needs the independent reviewer's
verdict and a **separate, explicit repin authorization** — it cannot ride along with the run
approval. **Not approved here.**

---

## OD-4 — Isolation contract for the real fit-and-freeze entry point

**Question.** The real campaign must fit its own model on scientific data before any test generation
(protocol `unresolved` U5; `data_roles.model_fitting` = "train windows only"). What isolation contract
must that entry point satisfy?

**Required contract (recommended shape).**
- **Authorization first:** an OD-2 document whose scope covers fitting; refuse otherwise, before any
  read.
- **Fresh, isolated output:** `resolve_output_dir` refuses protected directories, the frozen tree,
  v1 stage-0 artifacts and any directory holding campaign state; fit and freeze write to their own
  directory, creating no marker.
- **Provenance and clean tree:** `capture_provenance` with the five manifest hashes, offsets hash,
  protocol pin, commit and dirty state; `require_clean_tree` refuses a dirty tree.
- **Fit-split exclusion, enforced not promised:** only `train`/`val` rows; `assert_fit_splits` runs
  before feature use; any row tagged for the real *test* artifact is refused before feature
  extraction; no function in the fit path may take a directory containing `trials_test.csv` or a
  `test_access.json` marker; no read of `trials_test.csv` at any point.
- **Frozen contract reuse:** the same nine-key payload (including `detector_thresholds`),
  `freeze_fitted_v21` with provenance, and `load_fitted_v21` verification — no parallel artifact
  format.
- **Interruption is terminal:** a partially written fitted artifact must never be adopted; the
  freeze is all-or-nothing and hash-recorded.

**Alternatives.**
- **(a) Dedicated guarded entry point** (e.g. `fit_real`) sharing the freeze contract and the
  provenance helpers with B1, with the exclusions above machine-checked.
- **(b) A mode flag on B1's existing `fit_synthetic`.** Rejected: it widens the blast radius of the
  synthetic guard and risks an accidental real fit inside the test suite.
- **(c) Reuse the synthetic fitted artifact.** Already prohibited (D2 / protocol U5).

**Consequences.** (a) costs a new module, focused tests and a review; it keeps the synthetic path
provably untouched. (b) saves code but makes every synthetic test a potential real-data entry point.
(c) would invalidate the evaluation's meaning.

**Technical recommendation.** (a), with the shared helpers factored rather than duplicated so the
two paths cannot drift.

**Who must approve.** Owner authorization to fit on scientific data (design decision row B4),
plus independent review of the code and its tests. The person who writes the code cannot be the sole
approver. **Not approved here.**

---

## Outstanding approvals

| # | Decision | Approver | Additional requirement |
|---|---|---|---|
| OD-1 | Source contract: code-level extension vs v2.4 | Owner + independent reviewer | A v2.4 choice needs a revision and a separate repin authorization |
| OD-2 | Form and content of the authorization document | Owner / PI, in writing | Hash recorded in markers, metrics and provenance |
| OD-3 | Readiness external vs protocol revision | Owner | A revision needs reviewer verdict + separate repin authorization |
| OD-4 | Real fit-and-freeze isolation contract | Owner + independent reviewer | Authorized scientific-data fitting (design row B4) |

Beyond these four, B7 remains blocked by missing capability that no decision supplies: no real
generator, no authorized fit path in code, no denominator-literal enforcement, and a dirty,
uncommitted tree.

## Verification performed for this brief

| Check | Result |
|---|---|
| 21 protected artifacts | 21/21 byte-identical |
| `protocol_v2_3.json` | `e1dc5cc9…c154`; `campaign_ready = false`, `execution_ready = false`; D1 unset |
| Campaign markers, trials, metrics in the repository | none |
| Git | HEAD `230c5ae8…`, 0 staged, no commits, `git diff --check` clean |
| Files changed by this brief | this report only |

No sealed-test data was read, no trial generated, no model fitted, no campaign run, and nothing was
staged, committed or pushed. This brief records open questions and technical recommendations; it
claims no owner approval.
