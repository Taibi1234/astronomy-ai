# Phase 11 — Stage A: Safe Execution Runner Report

Status: Stage A complete. Runner architecture and synthetic validation implemented. **No
real campaign execution path exists**, no model was fitted, no real trial was generated, no
sealed-test data was read, and nothing was staged or committed.

Authoritative interpreter: `webapp/backend/.venv/Scripts/python.exe` (Python 3.14.3).

---

## 1. Starting and ending Git state

| | Starting | Ending |
|---|---|---|
| HEAD | `230c5ae8c26b87abd719c09548a23beab8f37222` | unchanged |
| Branch | `main` | unchanged |
| Staged files | 0 | 0 |
| Tracked modifications | `generalization.py`, `phase11.py`, `run_phase11.py` (+78/−26) | unchanged |
| `git diff --check` | clean | clean |

Stage A added two untracked files and one report; it modified no existing tracked or
untracked file. Existing uncommitted work from earlier stages is preserved untouched.

## 2. Files added

| File | SHA-256 | Lines |
|---|---|---|
| `webapp/backend/research/phase11_runner.py` | `331b983bde34cc465e7a0cf6e7e343c11491507db1b7a202b0645ab2d570ee35` | 417 |
| `webapp/backend/tests/test_phase11_stageA_runner.py` | `c4cdb5893783caa18047c32de41ceb0d0cdb50a7dc69f4803049693b6331b751` | 418 |
| `reports/phase11_stageA_runner_report.md` | this report | — |

No changed files outside this pair and this report.

## 3. Architecture and safety boundaries

`research/phase11_runner.py` exposes exactly two modes: `preflight` and `synthetic`.
`execute_real()` exists only to refuse.

| Property | Implementation |
|---|---|
| **Explicit modes** | `MODES = ("preflight", "synthetic")`. The CLI rejects every other string with exit 2 and a message stating that real execution needs a separate authorization. |
| **Protocol identity** | Delegates to `phase11_v2.campaign_preconditions` → `load_protocol_v21`, which enforces filename, exact SHA-256, sidecar, version, schema, 16 sections and operative invariants, with no fallback. |
| **Preflight-only failure** | Order is: output isolation → protocol identity → manifest/offset hashes → marker and fitted-artifact absence → provenance → clean tree. All of this happens before any trial artifact could be touched; preflight writes nothing (`list(out.iterdir()) == []`). |
| **Input provenance** | `capture_provenance` records commit/branch/dirty paths, protocol and offsets hashes, all manifest hashes, source-manifest hash, interpreter and package versions, platform and timestamp. The runner adds `configuration_sha256` over the resolved run configuration. |
| **Output isolation** | `resolve_output_dir` refuses: the manifest tree and anything inside it; the three protected directories; any directory already holding a frozen artifact; any directory holding campaign state; and any directory with v1 stage-0 files (version isolation). Only then does it proceed. |
| **One-shot access** | Reuses `research/test_access.py` unchanged. The synthetic walkthrough claims generation, completes it, claims access, completes it, and proves a second claim is refused. A four-process race is exercised at runner level. |
| **Generated-file integrity** | `verify_generated_trials` requires a *completed* generation marker with a 64-hex `trials_sha256`, then recomputes the hash of `trials_test.csv` and compares. Tampering, missing files, and `started`/absent markers all raise `IntegrityError`. |
| **No caller-supplied data** | `load_authorized_trials(out_dir)` takes only a directory — its signature has no data parameter, so unverified rows cannot be injected. It verifies the hash and the recorded row count before returning a frame. |
| **Version isolation** | The runner imports only `phase11_v2`, `safeguards`, `test_access`, `errors`; it never imports or calls `phase11.evaluate_test`, `run_campaign`, or `run_phase11.run_smoke` (asserted by a source test). A v1 stage-0 output directory is refused. |
| **Reproducible failures** | Typed hierarchy: `RunnerError(GateError)` → `ReadinessError`, `IntegrityError`, `OutputIsolationError`; every message names the failing condition and the required action. No fallback path anywhere. |

`execute_real()` refuses unconditionally: it reports the protocol's readiness blockers when
it can read them, appends "protocol readiness flags alone are not execution authorization",
and always appends "Stage A permits preflight and synthetic validation only". Even a future
flag flip cannot make Stage A execute.

## 4. Tests executed

```
cd webapp/backend
.venv/Scripts/python.exe -m pytest tests/test_phase11_stageA_runner.py -q
→ 32 passed            (after A.1 hardening; 29 after the isolation fix; 21 initially)

.venv/Scripts/python.exe -m pytest \
  tests/test_phase11_stageA_runner.py tests/test_phase11_access_closure.py \
  tests/test_phase11_protocol_repin.py tests/test_phase11_stage4_guards.py -q
→ 89 passed

ruff check research/phase11_runner.py tests/test_phase11_stageA_runner.py → All checks passed
ruff format --check (same two files)                                      → already formatted
git diff --check                                                          → clean
```

Historical runs, kept for the record: 29 passed (isolation fix) and 189 passed across seven
safety files (before the isolation fix).

Coverage of the required cases:

| Requirement | Test |
|---|---|
| synthetic preflight succeeds without fitting or sealed access | `test_preflight_succeeds_but_reports_the_readiness_blockers` |
| readiness gates prevent real execution | `test_execute_real_refuses_with_readiness_reasons`, `test_execute_real_refuses_even_without_inputs`, `test_runner_modes_exclude_real_execution`, `test_cli_refuses_modes_outside_stage_a` |
| bad protocol bytes / sidecars / versions / invariants rejected | `test_preflight_fails_closed_on_pin_mismatch` (the full loader matrix is covered by `tests/test_phase11_protocol_repin.py`) |
| protected output destinations rejected | `test_preflight_refuses_protected_and_frozen_tree_outputs`, `test_preflight_refuses_v1_stage0_and_campaign_state_outputs` |
| concurrent access permits one claimant | `test_concurrent_claims_allow_exactly_one_winner` (four subprocesses) |
| interrupted/malformed state blocks | `test_verify_requires_a_completed_generation_record`, `test_malformed_access_marker_blocks_the_runner`, `test_walkthrough_is_not_repeatable` |
| tampered generated bytes fail integrity | `test_tampered_trial_bytes_fail_integrity`, `test_missing_trial_file_fails_integrity` |
| provenance mismatches fail closed | `test_preflight_fails_closed_on_dirty_tree`, `test_preflight_fails_closed_on_a_missing_source_entry` |
| legacy paths not invoked | `test_runner_does_not_reference_legacy_entry_points` |
| no real trial files created | walkthrough assertions confine every write to `tmp_path`; no artifact exists under `reports/` |

## 5. Synthetic-only proof

- The only data the walkthrough writes is generated in memory by `_synthetic_frame`
  (trial ids `SYN-###`, a literal `source="synthetic-fixture"` column) and saved to
  `tmp_path/campaign/trials_test.csv`.
- No Kepler/TESS file is opened, no detector is run, no model is instantiated or fitted;
  `synthetic_walkthrough` returns `reads_sealed_data: False` and `fitted_model: False`.
- The preflight tests read only the frozen protocol, manifests and offsets (read-only
  hashing); they never open a trial file.
- `find reports -name test_generation.json -o -name test_access.json -o -name
  trials_test.csv -o -name metrics_test.json` → no matches after the run.

## 6. Confirmation: nothing scientific executed

No campaign, no fitting, no threshold calibration on real data, no real trial generation,
no evaluation, no sealed-test access, no legacy entry point invoked, and no historical smoke
output reused. Every marker created during testing lived under the pytest temporary
directory and is gone with it.

## 7. Protocol readiness limitation

The authorized protocol v2.3 is `phase11b-protocol-v2.3-proposal` with
`campaign_ready: false`, `execution_ready: false`, and status text stating it is not
authorized for execution. The runner reports four blockers:

1. `campaign_ready is not true`
2. `execution_ready is not true`
3. `protocol status declares it is not authorized for execution`
4. `proposal_record declares it is not authorized for execution`

This is the correct behaviour: adopting the code pin did **not** flip readiness, and the
runner treats the pin as identity, not authorization. The frozen protocol was not edited.

## 8. Protected-artifact integrity

- **21/21 protected artifacts byte-identical** to the pre-Stage-2 baseline.
- `protocol.sha256`, `offsets.sha256`, `protocol_v2_3.sha256` all verify.
- `protocol_v2_3.json` remains `e1dc5cc9ed4e6e2dc4645a82efc4f7638fb0f3128248b9810c67ba339f32c154`.
- No marker, trial file or metrics artifact exists anywhere under `reports/`.

## 9. Remaining risks and Stage B prerequisites

1. **No real execution implementation exists.** `execute_real` is a refusal stub; Stage B
   would need an actual campaign path behind the same gates, and that path must be reviewed
   independently before any run.
2. **Readiness flags are still false.** A Stage B authorization must decide how readiness is
   declared. Flipping flags inside the frozen v2.3 is not possible without a new protocol
   version (v2.4), which is a separate decision.
3. **Refusal audit trail not persisted.** The design note suggests writing refusal records
   outside the protected tree; Stage A prints to stderr only. This was not in the required
   property list and remains open.
4. **`load_authorized_trials` has no consumer yet.** The contract is implemented and tested,
   but no evaluator exists to use it; wiring one is Stage B work.
5. **CLI temp-directory default is untested.** With `--mode synthetic` and no `--out`, the
   CLI creates a system temp directory. Tests always pass an explicit directory; the default
   path is code-reviewed but not exercised.
6. **Sources remain untracked at HEAD**, so provenance is hash-based rather than
   commit-based.
7. **Protocol text still says "proposal only"**, which is now inconsistent with adoption by
   pin. This is documented in the repin report and needs a v2.4 to clear.
8. **TOCTOU residual.** Output validation and directory creation cannot be made atomic with
   `pathlib`. A.1 re-validates the created directory before any marker or trial file is
   written, so a hostile swap can leave at most an **empty directory**; removing the window
   entirely needs descriptor-relative (`dir_fd`) operations and is out of proportion here.
9. **Preflight still takes roots as arguments.** That path is read-only and must be able to
   load a specified protocol, so root parameters cannot weaken a write guard. Only the write
   path (`synthetic_walkthrough`) was made canonical in A.1.

Stage B is not started. No staging, commit or push was performed.

## 11. Stage A.1 — final safety hardening

Three concerns remained after the isolation fix; all three are addressed here without
changing any scientific behaviour.

### 11.1 Production callers can no longer supply arbitrary roots

`synthetic_walkthrough(root_dir, *, rows=6)` is now the only public entry point and derives
its roots from `gen.project_root()`; it accepts no repository or manifest root. The previous
implementation, which took `manifest_dir` / `repo_root` parameters, moved to the private
`_synthetic_walkthrough(...)`, documented as a test seam and deliberately excluded from
`__all__`. The CLI calls the public wrapper, so `--manifest-dir` / `--repo-root` no longer
influence synthetic output isolation.

### 11.2 The frozen-directory test can no longer write into the real tree

The tests that passed the real `reports/phase11_generalization`, its `smoke` and quarantine
subdirectories now use a disposable replica (`_replica()` in the test module) with its own
`reports/phase11_generalization/{smoke,smoke_invalid_scope_20261022}`. The real path is still
covered, but only through `resolve_output_dir`, which is read-only, so a regression can no
longer create `campaign/` inside the frozen tree.

### 11.3 TOCTOU between validation and creation

`_synthetic_walkthrough` now re-validates after `mkdir`: it re-resolves the created
`campaign` directory, requires it to remain inside the validated root, and re-runs
`resolve_output_dir` on it before any marker or trial file is written. A swap between
validation and creation can leave at most an empty directory; it cannot place a marker,
`trials_test.csv`, or any protected-directory artifact. The residual window is documented in
§9 item 8.

### 11.4 Tests changed

| Test | Status |
|---|---|
| `test_public_walkthrough_has_no_root_parameters` | new — signature is `(root_dir, rows)`; seam not exported |
| `test_public_walkthrough_uses_canonical_roots` | new — public API refuses a replica frozen tree via the patched project root |
| `test_canonical_guard_refuses_the_real_frozen_dir_without_writing` | new — real path refused by the read-only guard; no `campaign/` created |
| `test_test_seam_rejects_protected_directories[smoke, smoke_invalid_scope_20261022]` | rewritten onto the replica |
| `test_test_seam_rejects_a_path_alias_into_the_frozen_tree` | rewritten onto the replica |
| `test_synthetic_walkthrough_rejects_a_symlinked_parent` | moved onto the replica and the seam |
| `test_synthetic_walkthrough_rejects_a_symlinked_campaign_subdirectory` | new — a `campaign` symlink escaping the root is refused |
| `test_rejected_walkthrough_leaves_the_replica_unchanged` | rewritten — replica files hash-identical, directory listing unchanged |
| `test_synthetic_walkthrough_rejects_a_file_destination` | unchanged (already used a temp file) |
| `test_temporary_destination_still_succeeds` | unchanged (public API) |

### 11.5 Verification

```
.venv/Scripts/python.exe -m pytest tests/test_phase11_stageA_runner.py -q                     → 32 passed
.venv/Scripts/python.exe -m pytest tests/test_phase11_stageA_runner.py \
  tests/test_phase11_access_closure.py tests/test_phase11_protocol_repin.py \
  tests/test_phase11_stage4_guards.py -q                                                      → 89 passed
ruff check + ruff format --check (both files)                                                 → clean
git diff --check                                                                              → clean
```

- 21/21 protected artifacts byte-identical; `protocol_v2_3.json` still
  `e1dc5cc9ed4e6e2dc4645a82efc4f7638fb0f3128248b9810c67ba339f32c154`.
- No `campaign/`, marker, `trials_test.csv` or `metrics_test.json` anywhere under `reports/`.
- HEAD unchanged, 0 staged, no new commits.


## 10. Post-review fix: direct-API output isolation (Stage A, narrow) — HISTORICAL

> **Superseded by §11 (A.1).** This section is a historical record of the first isolation
> fix. It is accurate for the state at that time only: A.1 removed the `manifest_dir` /
> `repo_root` parameters described below (§11.1) and replaced the seven test functions with
> ten, eleven collected (§11.4). Current test names and counts are in §11.4; current
> signatures are in §11.1. The rows marked *superseded* below must not be read as the
> present design.

An independent read-only review found one gap: `synthetic_walkthrough()` wrote
`campaign/`, marker files and `trials_test.csv` without calling the output-isolation
safeguards. The CLI resolved the destination first, so the CLI path was safe, but a direct
library call such as `synthetic_walkthrough(MANIFEST_DIR)` could have created artifacts
inside the frozen manifest tree. This section records the fix.

### What changed

| File | Change |
|---|---|
| `research/phase11_runner.py` | `synthetic_walkthrough()` now calls `resolve_output_dir()` **before** any `mkdir`, marker or file write, resolving the destination against the canonical project root (`gen.project_root()`), the frozen manifest tree, the three protected directories, campaign-state artifacts, v1 stage-0 artifacts and the file-destination rule. It also refuses a `campaign/` path that escapes the validated root. ~~The signature gained optional `manifest_dir` / `repo_root` parameters (defaults preserve existing callers), and the CLI now passes its own roots through.~~ **(superseded by §11.1: those parameters were removed; the public API now derives canonical roots and the CLI passes none.)** |
| `research/phase11_runner.py` | `resolve_output_dir()` now rejects a destination that exists but is **not a directory** (existing-file edge case). |
| `tests/test_phase11_stageA_runner.py` | ~~7 new test functions (8 collected)~~ **(historical; superseded by §11.4: 10 functions, 11 collected)** covering the required cases. |

### New regression tests (historical names — see §11.4 for current ones)

The test names and expectations in this table were valid when the section was written; A.1
renamed the write-capable cases onto a disposable replica and added new checks. §11.4 is the
authoritative list.

| Test | Asserts |
|---|---|
| `test_synthetic_walkthrough_rejects_the_frozen_manifest_dir` | real manifest dir refused before any write; no `campaign/` created |
| `test_synthetic_walkthrough_rejects_protected_directories[smoke, smoke_invalid_scope_20261022]` | protected directories refused before any write |
| `test_synthetic_walkthrough_rejects_a_path_alias_into_the_frozen_tree` | `…/smoke/../campaign_alias` resolves into the frozen tree and is refused; nothing created |
| `test_synthetic_walkthrough_rejects_a_file_destination` | existing file refused with "not a directory"; file bytes untouched |
| `test_synthetic_walkthrough_rejects_a_symlinked_parent` | a directory symlink resolving into a frozen-layout replica is refused (skips where symlinks are unavailable) |
| `test_rejected_walkthrough_leaves_protected_artifacts_unchanged` | five frozen manifests hash-identical before/after a refused call |
| `test_temporary_destination_still_succeeds` | a normal temporary destination still completes the full walkthrough |

### Verification of the fix

```
cd webapp/backend
.venv/Scripts/python.exe -m pytest tests/test_phase11_stageA_runner.py -q        → 29 passed
.venv/Scripts/python.exe -m pytest tests/test_phase11_stageA_runner.py \
  tests/test_phase11_access_closure.py tests/test_phase11_protocol_repin.py -q   → 60 passed
ruff check + ruff format --check (both files)                                    → clean
git diff --check                                                                 → clean
```

- 21/21 protected artifacts remain byte-identical to the baseline.
- No `campaign/`, `test_generation.json`, `test_access.json` or `trials_test.csv` exists
  inside the frozen tree after the suite.
- No protocol, readiness flag, model, scientific data or historical artifact was touched;
  the fix is confined to the runner and its tests.

### Effect on the earlier findings

The review's item 3 (output isolation bypassable through the direct API) is now closed. The
remaining review notes are unchanged and still apply: the TOCTOU window between hashing and
`read_csv`, the narrow scope of the legacy-reference source scan, and the fact that tests
were not independently re-executed during the review itself.
