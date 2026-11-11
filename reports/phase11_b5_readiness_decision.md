# Phase 11 Stage B5 — Readiness Decision Record

Repository: `%USERPROFILE%\astronomy-ai`
Design authority: `reports/phase11_stageB_design.md` §5.8 (B5 row) and §7 risk 4
Input: `reports/phase11_b4_review.md`, `reports/phase11_generalization/protocol_v2_3.json`
Decision: **external readiness not granted.** No v2.4 revision is proposed, no readiness flag
changes, and no execution authority is created. Nothing is staged, committed or pushed.

## 1. Decision

| Item | Value |
|---|---|
| decision kind | `external_readiness_not_granted` |
| protocol revision | none proposed; `protocol_v2_3.json` stays the pin (`e1dc5cc9…c154`) |
| `campaign_ready` | **false** (unchanged) |
| `execution_ready` | **false** (unchanged) |
| `authorizes_execution` | **false** |
| required approval | a separate B7 authorization document plus a clean, committed source baseline; any readiness revision would additionally need review and a repin |

B5 is a decision stage, so this record is its deliverable. The machine-checkable form is produced
by `phase11_b5.assess_readiness(...)`; it recomputes the cross-checks below on every call and
raises when they disagree, so the record cannot silently outlive the code it describes.

## 2. Contract agreement (checked, not assumed)

`phase11_b5._agreement_checks` verifies four contracts and refuses to record agreement otherwise:

| Contract | Status | Evidence |
|---|---|---|
| fitted state | agrees | nine-key payload including `detector_thresholds`; `freeze_fitted_v21` refuses a payload without it |
| denominator policy | agrees | evaluator minima equal the frozen `insufficient_data` values (3 clusters, 30 nulls, 20 injections per depth per stratum); campaign literals remain a real-campaign requirement |
| G12 refusal audit | agrees | `phase11_b3.record_refusal` writes to `reports/phase11_refusals`, outside the frozen tree |
| readiness gates | agrees | `MODES == ("preflight", "synthetic")`; `execution_blockers` still reports the protocol's proposal-only status |

A disagreement — fitted payload drift, denominator drift, a changed mode set, or a protocol that
claims readiness — raises `GateError` instead of producing a record. A protocol asserting
`campaign_ready`/`execution_ready` would therefore block B5 rather than authorize anything: a flag
is never treated as authority.

## 3. Outstanding requirements (why readiness is not granted)

1. **B6** — the minimum meaningful difference is unset, so conclusions stay descriptive-only and
   practical-superiority claims remain prohibited.
2. No **real-data campaign generator** exists; the B2 generator produces synthetic arrays only.
3. The frozen **denominator literals** (76 nulls, 72 injections per depth per stratum, five test
   clusters) are not enforced by any runner yet; B3 enforces only the minima and reports observed
   counts.
4. The **tracked tree is dirty** and the source baseline is uncommitted, so a defensible run
   record cannot be captured.
5. No **B7 authorization document** exists.

## 4. Documentation trap (design §7 risk 4)

The frozen protocol text still declares itself `PROPOSAL ONLY` and its `execution_ready_reason`
("the committed runner does not yet implement v2 threshold selection, one-way marker gates, or v2
provenance") predates the B0–B4 hardening, which implemented exactly those. The text is therefore
stale on capability but **correct on authority**: neither the text, nor a code pin, nor a passing
test suite authorizes a campaign. This record is the operative decision, and it says the flags
stay false. A future operator must require the B7 authorization, not infer readiness from code.

## 5. Files

| File | Change | SHA-256 |
|---|---|---|
| `webapp/backend/research/phase11_b5.py` | decision record + fail-closed contract checks (201 lines) | `4c7b7370d0fce5b7efcd9f00ce58c1e6b6bc7922ff1735ffc71de0ddfff1db95` |
| `webapp/backend/tests/test_phase11_b5.py` | 14 focused tests (189 lines) | `19103ef1348784ec1977d481c362b733c5a2cc81ae96822c07cdf24b4b9d5286` |
| `reports/phase11_b5_readiness_decision.md` | this record | see §6 |

No protocol, manifest, sidecar, fitted artifact, runner, readiness flag or historical artifact was
modified.

## 6. Verification

| Command | Result |
|---|---|
| `pytest tests/test_phase11_b5.py -q` | 14 passed (5.0 s) |
| `pytest` on 6 directly related files (B4, B3, B1, Stage B readiness, Stage A runner, protocol repin) | 132 passed (58.7 s) |
| `ruff check` / `ruff format --check` on both changed Python files | clean |
| 21 protected artifacts | 21/21 byte-identical |
| `protocol_v2_3.json` | `e1dc5cc9…c154`; `campaign_ready = false`, `execution_ready = false` |
| stray trials, markers or campaign artifacts | none |
| Git | HEAD `230c5ae8…`, 0 staged, no commits, `git diff --check` clean |

## 7. Not done, by instruction

B6 (MMD) and B7 (campaign authorization) were not started. No campaign, real trial, model fit on
scientific data, sealed-test access, protocol revision, staging, commit or push occurred.
