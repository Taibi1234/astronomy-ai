# Phase 11 — Protocol v2.3 Repin Report

Status: repin complete. No campaign, fitting, calibration, trial generation, sealed-test
access, runner wiring, staging, or commit occurred. Protocol JSON and sidecars were not
edited.

Authoritative interpreter: `webapp/backend/.venv/Scripts/python.exe` (Python 3.14.3).

---

## 1. Protocol identity verified before editing

25 pre-edit checks were executed and all passed; the repin would have aborted on any
failure.

| Check | Result |
|---|---|
| `protocol_v2_3.json` SHA-256 = `e1dc5cc9ed4e6e2dc4645a82efc4f7638fb0f3128248b9810c67ba339f32c154` | PASS |
| `protocol_v2_3.sha256` SHA-256 = `07950fc3a780e4b4c15abaa98fc50088dd1b68e0f4485a978d4e9d0b7ee7c2c3` | PASS |
| `sha256sum -c protocol_v2_3.sha256` | OK |
| `immediate_predecessor.sha256` = v2.2 `61f67198…f124814a` | PASS |
| `supersedes.sha256` = v1 `ded2bd5e…75319f` | PASS |
| version `phase11b-protocol-v2.3-proposal`, phase `11b`, schema 2 | PASS |
| target FPR 0.05, min calibration n 30, strict `>`, tolerance 0.0377, percentile bootstrap, MMD unset, marker names, 16 required sections | PASS (10 checks) |
| Recursive diff v2.2→v2.3 = 16 paths, all environment/provenance | PASS |
| Nine operative blocks byte-equal to v2.2 | PASS (9 checks) |

The recursive diff is confined to: `version`, `status`, `frozen_at`,
`input_verification.verified_at`, `immediate_predecessor.*`, `environment.*`,
`changelog_vs_v1[len]`, `proposal_record`. No operative rule changed.

---

## 2. Source change

Only the protocol pin and its documentation were changed. Hash verification was preserved
in full: sidecar check → exact pin check → phase/schema/version check → section check →
operative invariants.

`research/phase11_v2.py` (untracked file), constants block:

```diff
-AUTHORIZED_PROTOCOL_NAME = "protocol_v2_2.json"
-AUTHORIZED_PROTOCOL_SHA256 = "61f671986814b2b6d1f02d1d8da1e31e613ddc24ef1e545e54f68666f124814a"
-AUTHORIZED_PROTOCOL_VERSION = "phase11b-protocol-v2.2"
+AUTHORIZED_PROTOCOL_NAME = "protocol_v2_3.json"
+AUTHORIZED_PROTOCOL_SHA256 = "e1dc5cc9ed4e6e2dc4645a82efc4f7638fb0f3128248b9810c67ba339f32c154"
+AUTHORIZED_PROTOCOL_VERSION = "phase11b-protocol-v2.3-proposal"
```

Also updated for accuracy, with no behavioural effect: four docstring/message references in
`research/phase11_v2.py` ("protocol v2.2 loading", the pinned filename/hash in the module
docstring, "Load the authorized v2.2 protocol", "fitted state … protocol v2.2"), and one
docstring line in `research/run_phase11_v2.py` ("frozen v2.3 preflight").

No fallback acceptance was introduced: the loader accepts exactly one filename, one hash
and one version string.

| File | SHA-256 after change |
|---|---|
| `research/phase11_v2.py` | `5f79925ffe7c1c6bee6e1d5670bdce207fef4eaa9a7c8b80ca8c54a61cb2c080` |
| `research/run_phase11_v2.py` | `a5552514bf59432872197413683130b7f02416e5db4ede5267f33cc30f8280c9` |
| `tests/test_phase11_protocol_repin.py` (new, 12 tests) | `582b69ccdf5d5c2a7b6eb9b6dbca7b8e019eb8d780f950c4eeb261aee24c4f94` |
| `tests/test_phase11_v2_stage2.py` | `0e4b9c3715aaad257463c248f882699869d725135db7b4d34c76f4cee286e213` |
| `tests/test_phase11_v2_review.py` | `de112d1d3bb17595e8dd5f4f42f825cf3b33423ab03e770c9f5cc7d2b507849d` |
| `tests/test_phase11_stage3_safeguards.py` | `733bb6c3684c59638ee22fc65bf9d2c51123233b55be137888bdaa9b54a5db4a` |
| `tests/test_phase11_stage4_guards.py` | `03e74286a01d6e148128ab591f50287060584d66eab6d534f202aaed5119e932` |

Two tests were inverted deliberately, not deleted: the former
`test_v23_is_a_proposal_that_the_code_refuses_to_authorize` now asserts acceptance and
predecessor binding, and the former `test_implementation_stays_pinned_to_v2_2` now asserts
the v2.3 pin **and that v2.2 is refused**.

---

## 3. Tests executed

```
cd webapp/backend
.venv/Scripts/python.exe -m pytest tests/test_phase11_protocol_repin.py -q
→ 12 passed

.venv/Scripts/python.exe -m pytest \
  tests/test_phase11_protocol_repin.py tests/test_phase11_v2_stage2.py \
  tests/test_phase11_v2_review.py tests/test_phase11_stage3_safeguards.py \
  tests/test_phase11_stage4_guards.py tests/test_phase11_access_closure.py -q
→ 168 passed

ruff check (7 changed files)                → All checks passed
ruff format --check (3 core files)          → already formatted
```

The new focused file covers every required case:

| Requirement | Test |
|---|---|
| v2.3 accepted when hash and version match | `test_v23_is_accepted_when_hash_and_version_match` |
| changed byte rejected | `test_a_changed_byte_is_rejected` |
| wrong hash rejected | `test_wrong_expected_hash_is_rejected` |
| wrong version rejected | `test_wrong_version_string_is_rejected` |
| invalid/missing sidecar rejected | `test_invalid_or_missing_sidecar_is_rejected` |
| tampered invariant rejected | `test_operative_invariants_still_guard_a_tampered_protocol` |
| v2.2 and v2.1 not accepted by the new pin | `test_earlier_versions_are_not_accepted_by_the_v23_pin` |
| MMD unset and overrides refused | `test_mmd_remains_unset_and_overrides_are_refused` |
| no execution surface introduced | `test_no_execution_surface_was_introduced` |
| pin identity | `test_pin_constants_are_the_authorized_v23_identity` |
| frozen files untouched | `test_frozen_protocol_and_sidecar_are_unchanged_by_the_repin` |

No campaign, fitting, trial generation or sealed-test access was executed by any test; all
fixtures are synthetic copies in temporary directories.

---

## 4. Negative acceptance evidence

- `load_protocol_v21(protocol_v2_2.json)` → `GateError: … is not the authorized protocol`.
- `load_protocol_v21(protocol_v2_1.json)` → same.
- A one-byte change with the original sidecar → `does not match its recorded hash`.
- A recomputed sidecar over a tampered file with the default pin → `is not the authorized protocol`.
- Version string reverted to v2.2 with a matching sidecar → `protocol version … is not authorized`.
- Missing sidecar → `missing hash sidecar`; wrong sidecar digest → `does not match its recorded hash`.
- `min_calibration_n_per_stratum` changed to 50 with a matching sidecar → invariant failure.

---

## 5. No execution surface

`phase11_v2` still exposes no `evaluate_test`, `run_campaign`, `fit_models`, `run_smoke`
or `evaluate`. `run_phase11_v2.ENABLED_MODES == ("preflight",)` and no `--execute`
argument exists. No fitting, calibration run, trial generation or sealed-test read occurred
in this task; the focused suite uses only synthetic temporary fixtures.

---

## 6. Preservation and Git

- All six sidecars verify: `protocol.json`, `offsets.json`, `protocol_v2.json`,
  `protocol_v2_1.json`, `protocol_v2_2.json`, `protocol_v2_3.json`.
- `protocol_v2_3.json` remains `e1dc5cc9…9f32c154`; v2.2 remains `61f67198…f124814a`.
- **21/21 protected artifacts byte-identical** to the pre-Stage-2 snapshot (nine v1 inputs,
  v2/v2.1 pairs, eight smoke/quarantine files).
- No `trials_test.csv`, `test_generation.json`, `test_access.json` or `metrics_test.json`
  exists anywhere under `reports/`.
- Git: branch `main`, **0 staged**, `git diff --check` clean, HEAD `230c5ae8…`.
  Tracked modifications are the three files from earlier hardening stages and are
  unchanged by this task; the repin touched **untracked** sources
  (`research/phase11_v2.py`, `research/run_phase11_v2.py`) and tests, which is why
  `git diff --name-only` does not list them.

---

## 7. Unresolved issues

1. **The adopted protocol still says "proposal".** `protocol_v2_3.json` carries
   `status: "PROPOSAL ONLY, not authorized for execution"` and
   `proposal_record.status: "proposal; NOT authorized for execution"`. Adoption is recorded
   by the code pin and this report; clearing the wording requires a v2.4 artifact, which was
   not authorized.
2. **`campaign_ready: false` and `execution_ready: false` remain in the protocol.** They are
   accurate: no runner exists. Flipping them is a code+authorization matter, not a text edit.
3. **Stale internal name.** `load_protocol_v21` still carries a "v21" name while loading
   v2.3. Renaming it would touch every caller and was outside "update only the pin"; it is
   cosmetic and can be done in a later cleanup.
4. **Sources remain untracked at HEAD**, so provenance still rests on the source-manifest
   hash rather than a commit id.
5. **Sidecar coverage gap persists**: the five manifests still have no sidecars and are
   bound only inside the protocol artifacts.

No protocol JSON or sidecar was edited. Nothing was staged, committed or pushed.
