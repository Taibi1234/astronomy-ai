# Phase 11 — Final Safeguards, Verification, and Handoff Report

Repository: `%USERPROFILE%\astronomy-ai`
Baseline commit: `ae511b8fc09227ed8643ea3cc1bfffb40dfa5227` (verified before editing; HEAD unchanged at the end)
Branch: `main` (ahead of `origin/main` by 2 commits)
Status: **software hardening complete with one documented owner blocker (H3)**. No scientific result was
generated; the experiment remains unapproved and outside this task.

## Executive summary

- **Completed:** M-1 (generator feature-completeness gate), M2 (access-ledger binding), M3 (marker
  denominator consistency), M4 (uniform post-claim failure records with original exception types and
  metrics quarantine), M5 (approved authorization directory, symlink/escape refusal, 30-day zero-skew
  validity), L-1/L-2 (one-shot and concurrency evidence), L-3 (closed-schema fitted contract), L-4
  (marker re-read before observed-denominator use), and the H3 trust-model documentation.
- **Blocked:** H3 issuer authenticity — an owner decision. The digest proves byte integrity only; no
  signing key, registry or trust root was invented.
- **Owner action needed before any real run:** choose the trust model (H3), create the approved
  `authorization/` directory, and issue a real authorization document out of band.
- **Evidence:** 159 focused tests and 329 safe regression tests passed, Ruff check and format clean,
  `git diff --check` clean, 21/21 protected artifacts byte-identical, protocol pin unchanged, both
  readiness flags false.
- **Not ready for scientific execution:** the software gates are in place, but no authorization exists
  and H3 is unresolved. The scientific ceiling remains `descriptive_only`.

## Baseline and scope

| Item | Value |
|---|---|
| Baseline / final HEAD | `ae511b8fc09227ed8643ea3cc1bfffb40dfa5227` (unchanged) |
| Branch | `main`, ahead 2, 0 staged |
| Pre-existing working tree at start | 7 modified files (the prior uncommitted patch); preserved |
| Final working tree | 8 modified files (the same seven plus `tests/test_phase11_b3.py`), all unstaged |
| Diff summary | 1009 insertions, 108 deletions across the 8 files |
| `phase11.py`, `generalization.py` | byte-identical to HEAD (blob equality) |

Changed files and their final SHA-256 (first 16 hex):

| File | Change | SHA-256 |
|---|---|---|
| `webapp/backend/research/phase11_authz.py` | approved-directory + symlink/escape + data-tree exclusion; injectable clock; closed binding | `979ffad7300ceae1` |
| `webapp/backend/research/phase11_b3.py` | ledger binding, marker re-read, unified post-claim failure record, metrics quarantine | `37dd1339f71d1e3a` |
| `webapp/backend/research/phase11_b7.py` | passes `DocumentLocation` into the authorization loader | `3cac74d8f3af3ffb` |
| `webapp/backend/research/phase11_b7_generate.py` | M-1 required-feature gate; L-3 closed-schema fitted validation | `97ff69bb383a55ec` |
| `webapp/backend/tests/test_phase11_authz.py` | location/validity/symlink/boundary tests | `ef3077c23c0e7fd1` |
| `webapp/backend/tests/test_phase11_b3.py` | post-claim `IntegrityError` failure-record assertion | `7182a0516a0ee5b5` |
| `webapp/backend/tests/test_phase11_b7.py` | approved-dir fixture, temporary repo roots | `9b441590ebbea3bd` |
| `webapp/backend/tests/test_phase11_b7_generate.py` | M-1/M4/L-1/L-2/L-3/L-4 adversarial tests | `4037bad011445767` |

## Blocker-by-blocker results

### M-1 — generated feature completeness — **fixed**
`assert_generated_frame(..., required_features)` (`phase11_b7_generate.py`) now refuses a frame missing
any feature of the validated fitted contract, before `claim_generation` and before any file write.
Tests: `test_generator_refuses_a_frame_missing_a_fitted_feature` (no generation marker, no
`trials_test.csv`); the valid synthetic generation fixture still passes (41 generator tests).
Residual: the check covers the fitted feature list; a *new* scoring requirement introduced later
would need its own addition. No owner decision.

### M2 — access ledger binding — **fixed**
The access claim, the completion ledger and `metrics_test.json` all record `campaign_id`,
`authorization_sha256` and `source` from the validated generation marker
(`phase11_b3.py:551-552, 582-583, 650-651`). Tests assert all three in the successful evaluation path.

### M3 — marker denominator consistency — **fixed**
Expected denominators are compared with the evaluator's recomputation **before** the claim
(`_preclaim_generation_check`), observed denominators are recomputed from the verified trial file and
compared **before scoring**; the marker is re-read at that point (L-4). Tamper tests for expected and
observed fields pass; the expected-tamper case leaves the access marker `None`.

### M4 — post-claim failure handling — **fixed**
`_evaluate` now records a terminal failure for every ordinary exception after the claim, re-raises the
original type unchanged, and adds a note when the failure record could not be written. The record names
campaign, authorization digest, failure stage, error class, access-marker state and terminal status.
Metrics are quarantined to `metrics_test.failed.json` when an evaluation fails before ledger completion.
Tests: post-claim `GateError`, post-claim `IntegrityError`, unexpected `RuntimeError`, metrics-write
`OSError`, ledger-completion failure, failure-record write failure, and a second attempt after each
(refused as one-shot). `BaseException` is deliberately not caught; a hard kill can leave no failure file
(see residual risks).

### M5 — approved location and validity policy — **fixed**
`AUTHORIZATION_DIRNAME = "authorization"`; documents must resolve **directly** inside
`<repo_root>/authorization`, which must be inside the repository, outside the frozen manifest tree,
outside the protected directories and outside the scientific `data/` tree. Symlinked documents,
`..` traversal and approved directories inside those forbidden trees are refused.
Validity: timezone-aware only, `issued_at ≤ now ≤ expires_at`, at most `MAX_VALIDITY_DAYS = 30`, zero
clock skew, injectable clock for tests. Tests cover valid placement, outside-directory, traversal,
symlinked document, approved-directory escape, frozen-tree and data-tree placement, malformed/naive
timestamps, `+05:30` offsets, exact-expiry, just-after-expiry, future-dated, inverted and over-30-day
intervals, and missing expiry.

### L-1 / L-2 — failure evidence and one-shot integrity — **fixed (evidence best-effort by design)**
Claims are created with exclusive creation, have no deletion/reset path, and a failure to write metrics,
the ledger or the failure record never restores the claim. A B3-level two-thread test proves exactly one
evaluation acquires the claim; a second sequential attempt is refused after every failure mode above.
Failure-record loss is surfaced through the exception note, not silently.

### L-3 — strict fitted-contract validation — **fixed**
Closed schema: the seven frozen metadata keys are the only permitted extras (`phase`, `schema_version`,
`protocol_version`, `protocol_sha256`, `model_sha256`, `provenance`, `_sha256`); any other extra key is
refused. Types for `model_id`/`dropped_features`, known feature names, medians-length/type, non-empty
finite threshold and detector tables, stratum coverage of the protocol `noise_conditions`, positive and
internally consistent counts, and the model-file reference are all validated before rows are built.
Tests: extra key, wrong `model_id` type, wrong `dropped_features` type, zero counts, `train_injected >
train_rows`, non-finite threshold, missing strata, missing model file, unknown feature, medians mismatch.

### L-4 — marker and denominator consistency — **fixed**
The marker is re-read (`require_generation_marker`) immediately before the observed-denominator check;
missing `observed_denominators` is refused. Tests: altered expected, altered observed, missing observed.

### H3 — issuer authenticity — **unresolved (owner decision)**
Documented in `phase11_authz` and below. No trust root was invented; the code does not claim the digest
authenticates an issuer.

## Security review

- **One-shot claim:** `claim_access` runs before the first trial read, uses `O_CREAT|O_EXCL`, and no
  code path deletes or resets it. Pre-claim marker validation prevents a mismatched marker from burning
  the claim. Concurrency test: `test_concurrent_evaluations_acquire_the_claim_once` (one success, one
  refusal). A hard process kill can leave `started` with no failure record — fail-closed, documented.
- **Authorization document path:** approved directory is `<repo>/authorization`; symlinked document,
  parent escape, frozen-tree, protected-directory and scientific-data placement are refused.
- **Time validity:** aware timestamps only, UTC comparison, expiry/future/inverted/>30-day rejected,
  zero skew, injected clock in tests.
- **Binding consistency:** fit provenance, generation marker, rows, access ledger and metrics all carry
  the campaign id and document digest; the binding also records all five manifest digests, the protocol
  hash and `expires_at`.
- **Denominators:** recomputed from hash-verified manifests/config/offsets, compared against the frozen
  literals, per stratum and per `(stratum, depth)` cell, both before the claim and before scoring.
- **Fitted contract:** validated before any input row is processed; closed schema; strata coverage.
- **Post-claim failures:** uniform terminal record, original exception preserved, metrics quarantined,
  one-shot preserved; audit-loss surfaced via exception note.
- **Issuer authenticity:** byte integrity only. The digest can be produced by anyone who can run the
  code; a real campaign relies on some external decision of trust (below).

## Verification results (actually executed)

| Check | Command | Result |
|---|---|---|
| Focused suites | `pytest tests/test_phase11_authz.py tests/test_phase11_b7.py tests/test_phase11_b7_generate.py tests/test_phase11_b3.py -q` | **159 passed**, 37.6 s |
| Safe regression | `pytest` over B0, B1, B2, B2a ×2, B4, B5, B6, CLI, hardening, Stage A runner, Stage B readiness, protocol repin | **329 passed**, 43.5 s |
| Ruff lint | `ruff check` on the 8 changed files | All checks passed |
| Ruff format | `ruff format --check` on the 8 changed files | 8 files already formatted |
| Whitespace | `git diff --check` | clean |
| Protected artifacts | 21 baseline hashes | **21/21 byte-identical** |
| Protocol pin | SHA-256 of `protocol_v2_3.json` | `e1dc5cc9…c154` (unchanged) |
| Readiness | `campaign_ready`, `execution_ready`, D1 | `false`, `false`, `null` |
| Frozen dependencies | `phase11.py`, `generalization.py` blobs vs HEAD | identical |
| Scientific artifacts on disk | search for trials/metrics/markers/fitted/authorization/failure files | none outside the historical smoke evidence |

Safety of the regression set: all 13 files were inspected; they use synthetic fixtures, frozen
manifests and temporary directories. One B7 test hashes the real **train** quarter `Q00` file
(`test_real_fit_quarter_integrity_matches_the_frozen_manifest`) to exercise the integrity reader; it
reads no held-out data and performs no fitting, and it skips when the file is absent.

## Residual owner decisions

1. **H3 issuer trust model (blocking for a real run).** Options and implications:
   - *Out-of-band approval + controlled placement by the owner* (current design): simplest, no new
     machinery; the owner must distribute the digest through an authenticated channel and create the
     document in `authorization/`. Failure mode: a mistaken or malicious local operator can mint a
     valid document; detection relies on human process and Git review.
   - *Digital signatures with a pinned public key*: strong non-repudiation; requires key management,
     a rotation policy and a verifier; failure mode: key loss/compromise, and the trusted key becomes
     the new root.
   - *Managed issuer registry / authorization service*: central control and revocation; requires
     infrastructure and availability guarantees; failure mode: service compromise or unavailability
     blocks legitimate runs.
   Until one is chosen, the digest must not be described as issuer authentication.
2. **Approved directory confirmation.** This task selected `<repo>/authorization` (constant
   `AUTHORIZATION_DIRNAME`). The owner should confirm the name and create the directory before any real
   document exists; no authorization document was created here.
3. **Validity policy** is implemented exactly as authorized (30 days, zero skew); no further decision
   pending. A future change requires owner approval.

## Final handoff

- **Changed files (8, unstaged):** `research/phase11_authz.py`, `research/phase11_b3.py`,
  `research/phase11_b7.py`, `research/phase11_b7_generate.py`, `tests/test_phase11_authz.py`,
  `tests/test_phase11_b3.py`, `tests/test_phase11_b7.py`, `tests/test_phase11_b7_generate.py`.
- **Git:** HEAD unchanged at `ae511b8…`, 0 staged, no commit, no push; all pre-existing untracked work
  (reports, smoke evidence, other modules, frontend, backups, data, venv) preserved.
- **Boundaries:** no model fitting, no held-out/test-quarter access, no real trial generation, no
  real-artifact evaluation, no campaign execution, no authorization document created.
- **Recommended next step:** owner decides H3 and the approved-directory name, creates
  `authorization/`, then authorizes a separate review/commit of these eight files; only after that and
  a real authorization document should the (still separately approved) scientific run be considered.
