# Phase 11 — Addendum: authorization-clock repair

Date: 2026-10-28
Repository: `C:\Users\5CA\astronomy-ai`
Branch: `main`, HEAD `ae511b8fc09227ed8643ea3cc1bfffb40dfa5227` (unchanged by this repair)
Applies to: `reports/phase11_final_hardening_report.md`

## 1. Purpose and standing of the original report

`reports/phase11_final_hardening_report.md` documents the Phase 11 safeguards hardening and
records the state of the working tree **before** the repair described here. It remains the
authoritative record of that work. Two of the file hashes in its handoff table are now
superseded — `research/phase11_authz.py` and `tests/test_phase11_authz.py` — and this addendum
is the authoritative record of their post-repair values.

The hardening report was **not** edited. A hash mismatch against its table is expected and is
not evidence of tampering; it is the reason this addendum exists.

Nothing here changes authorization policy, gate ordering, protocol data, frozen artifacts or
readiness. No scientific run was performed and none is authorized.

## 2. The defect

`tests/test_phase11_authz.py::test_valid_document_loads_and_binds` failed after 2026-10-24.

- The fixture set `FIXED_NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)`.
- `_doc()` derived `issued_at = FIXED_NOW - 1h` and `expires_at = FIXED_NOW + 23h`, so the
  document expired at **2026-10-24T11:00:00Z**.
- `load_authorization_document` called `_assert_validity(document)` with no clock argument, so
  the validity check fell back to `datetime.now(UTC)` (`phase11_authz.py:111`).
- Observed failure: `research.errors.GateError: authorization expired at 2026-10-24T11:00:00+00:00`.

The test could therefore pass only inside a 23-hour window. Any reviewer cloning the repository
after that window would see a red suite. This was a test/API design defect, not a regression in
the hardening logic: the expiry rule itself behaved correctly.

Related coverage gap: expiry refusal had been exercised only through the private
`_assert_validity(...)`, never through the public `load_authorization_document` path.

## 3. The repair

Confined to two files, three hunks. `_assert_validity` already accepted `now`; the public loader
did not forward it.

**`webapp/backend/research/phase11_authz.py`**

1. Added an optional keyword-only parameter `now: datetime | None = None` to
   `load_authorization_document`, with a docstring note that it exists for tests and that
   production callers must omit it.
2. Forwarded it at the existing call site: `_assert_validity(document, now=now)`.

Because the default is `None` and `_assert_validity` already resolves
`current = now or datetime.now(UTC)`, omitting the argument is behaviourally identical to the
previous code. Gate ordering is unchanged; validity remains the last check.

**`webapp/backend/tests/test_phase11_authz.py`**

3. `test_valid_document_loads_and_binds` now passes its existing `FIXED_NOW` explicitly
   (`_load(ref, tmp_path, now=FIXED_NOW)`), removing the wall-clock dependency.
4. Added `test_expired_document_is_refused_through_the_public_loader`, which asserts an expired
   document is refused through `load_authorization_document` — closing the coverage gap above.
5. Added `test_production_callers_never_inject_the_validity_clock` (guard test, see §4).

## 4. Production callers

Three production call sites exist, and **none passes `now=`**:

| Caller | Line | `now=` passed |
|---|---|---|
| `webapp/backend/research/phase11_b3.py` | 430 | no |
| `webapp/backend/research/phase11_b7.py` | 87 | no |
| `webapp/backend/research/phase11_b7_generate.py` | 452 | no |

There is no HTTP route, environment variable, CLI argument or runtime configuration that reaches
this parameter. All three callers use keyword arguments only and omit it, so they inherit the
real UTC clock exactly as before.

**Guard test.** `test_production_callers_never_inject_the_validity_clock` parses every
`research/*.py` file with `ast`, skipping `phase11_authz.py` itself, locates each
`*.load_authorization_document(...)` call and asserts no `now` keyword is supplied. It also
asserts at least three call sites were found, so it cannot pass vacuously if the call sites are
renamed. It uses AST parsing rather than text matching, and is scoped to `research/` only.

## 5. Verification

The distinction below matters: this addendum is documentation-only and re-ran nothing. Values
marked *verified* were measured read-only while writing this addendum; the test result was
observed in the Phase 1B run and is not re-attested here.

| Item | Status |
|---|---|
| Post-repair hashes of the two changed files | **verified** (recomputed read-only) |
| `reports/phase11_final_hardening_report.md` unmodified | **verified** |
| Readiness flags and protocol pin | **verified** |
| Production caller inventory (§4) | **verified** by static inspection |
| HEAD, staged count, working-tree counts | **verified** |
| External snapshot integrity (10/10 manifest entries) | **verified** |
| Focused test result (44 passed, exit 0) | **observed** in the Phase 1B run, not re-run here |
| The hardening report's "159 passed" claim | **reported earlier; now stale** — superseded, see §6 |

## 6. Test result

Observed when the Phase 1B run executed the authorized focused suite:

```
tests/test_phase11_authz.py  →  44 passed, exit code 0
```

**Only `tests/test_phase11_authz.py` was run.** The command used
`PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider` in the existing backend virtual
environment. No other test file was executed; in particular the four suites that perform fitting,
trial generation or evaluation were deliberately not run, so their state is unchanged and not
re-attested by this addendum.

For comparison, the same file reported `41 passed, 1 failed` immediately before the repair. The
net `+2` tests are the two added in §3.

The "159 passed" figure in the hardening report described a different, larger set of suites on
2026-10-24 and should not be read as a current result.

## 7. Hashes

Post-repair (current, full SHA-256):

| File | SHA-256 |
|---|---|
| `webapp/backend/research/phase11_authz.py` | `d83cf965103c8a39a5101e4f1ade191d3d63d69bbc01405e85ce01af950488f6` |
| `webapp/backend/tests/test_phase11_authz.py` | `a2f7f0505acf885be60b686a5f03844cf1f28e014620ecec4753ffc94efc7369` |

Pre-repair values, for reconciliation with the hardening report and the external snapshot:

| File | SHA-256 (pre-repair) |
|---|---|
| `webapp/backend/research/phase11_authz.py` | `979ffad7300ceae1af46a5dad9f71b4ad7543e6bae9a70053c55986a72fc48df` |
| `webapp/backend/tests/test_phase11_authz.py` | `ef3077c23c0e7fd12055f477feb2a1ff5a9389307a9fa6250201f5a46c5ceeb3` |

The six other files touched by the hardening change are unaffected by this repair
(`phase11_b3.py`, `phase11_b7.py`, `phase11_b7_generate.py`, `test_phase11_b3.py`,
`test_phase11_b7.py`, `test_phase11_b7_generate.py` — their reviewed hashes still hold).

## 8. Readiness — unchanged

| Flag | Value |
|---|---|
| `campaign_ready` | `false` |
| `execution_ready` | `false` |
| `protocol_fields_open` | `[]` |
| Scientific ceiling | `descriptive_only` |

Protocol pin `reports/phase11_generalization/protocol_v2_3.json`
= `e1dc5cc9ed4e6e2dc4645a82efc4f7638fb0f3128248b9810c67ba339f32c154` (unchanged).

The clock parameter added in §3 is a test seam only. It does not authorize execution, does not
alter the expiry policy (`MAX_VALIDITY_DAYS = 30`, zero skew), and does not move either readiness
flag. The scientific ceiling remains `descriptive_only`; the H3 issuer-authenticity decision
remains open and unresolved.

## 9. Git and snapshot state

- No Git write occurred in this work: no `add`, `commit`, `push`, `stage`, `stash`, `reset`,
  `clean`, or branch change. HEAD remains `ae511b8fc09227ed8643ea3cc1bfffb40dfa5227`, staged
  files remain 0.
- The external pre-repair snapshot at
  `C:\Users\5CA\phase11-hardening-preserved\20261028\` was **not modified**. Its manifest still
  verifies 10/10, and its stored copies remain the pre-repair bytes listed in §7 — so the repair
  is fully reversible by restoring those two files.

## 10. Not covered by this addendum

- No re-run of the withheld suites (fitting, generation, evaluation, campaign paths).
- No change to, or review of, the H3 issuer-authenticity decision.
- No authorization to commit, publish, or execute the campaign. Those remain separate decisions.
