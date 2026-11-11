# Phase 11b Stage 2 — Hardening Implementation Report

Status: implemented and verified with synthetic-only tests. No campaign was executed, no
model was fitted, no test trial was generated, no sealed test row was read, and nothing was
staged, committed or pushed.

Protocol targeted: `reports/phase11_generalization/protocol_v2_1.json`,
SHA-256 `bae1cc583e6dc85f5190c430ed55de8d2799bf994cac03d40ce7a3b423e21a80`.

## 1. Files changed

| Path | Lines | SHA-256 | Status |
|---|---|---|---|
| `webapp/backend/research/phase11_v2.py` | 1020 | `dbd187f14cc4f0c37a3d8708e6af2c4d3c698e543bb6a1629125aa2fb27c144b` | new, untracked |
| `webapp/backend/tests/test_phase11_v2_stage2.py` | 844 | `9e02a1b16dbdfa6f10bd922dc8c0556bd9dc94ea72e880a9d2cf52731fc63df6` | new, untracked |

No existing file was modified. `research/phase11.py`, `research/run_phase11.py`,
`research/generalization.py` and `research/core.py` are byte-identical to the committed
baseline, so the v1 historical path and every previously verified behaviour are unchanged.

## 2. What was implemented

**Protocol loading and validation.** `load_protocol_v21` requires four independent checks:
sidecar match, the exact authorized SHA-256, phase `11b` / `schema_version 2` / version
string, and the presence of 16 required sections. It then re-checks the operative values
(target FPR 0.05, minimum calibration sample 30, strict `>` comparison, 0.0377-day
tolerance in both the decision record and the recovery text, validation-only L7
calibration, per-noise reporting, percentile-primary bootstrap, unset MMD, both marker
names). A hash alone is never accepted as proof of content.

**Manifest validation** (`validate_manifests`) verifies all five manifests against the
protocol's bound hashes, the `11a` phase header, required structural keys, and the
5.0-day / 3.0-day window lengths plus per-window record keys. `null_library.json` is the
documented exception: it has no phase header, so a phase field is validated only when
present.

**v2.1 threshold algorithm** (`choose_threshold_v21`). q = linear (1−α) quantile;
`floor_binding = floor > q` (strict); `t0 = max(q, floor)`; candidates = `{t0} ∪ observed ≥ t0`;
threshold = smallest candidate with `#{scores > t} / n ≤ 0.05`; `threshold_source` precedence
`tie_lift` → `floor` → `quantile`; records n, q, t0, floor, exceedance, distinct-score count.
Minimum sample 30 enforced per stratum; non-finite scores dropped, not counted.

**Operability and calibration gates.** `calibrate_thresholds_v21` refuses test rows in the
calibration frame, refuses undeclared or missing strata, and refuses a stratum below the
minimum. `threshold_degenerate` marks a threshold at or above the score supremum (probabilities:
1.0), and `assert_strata_operative` fails closed on any degenerate stratum — a degenerate
threshold satisfies the exceedance bound but has no usable operating point, and the two are
reported separately.

**Atomic one-way markers.** `begin_marker` creates `test_generation.json` / `test_access.json`
with `O_CREAT|O_EXCL` in state `started`; `complete_marker` performs the single permitted
transition `started → completed` by atomic replace. Any pre-existing marker in any state,
including `invalid`, refuses; a simulated concurrent create refuses; there is no code path
that deletes, resets or reuses a marker (asserted by a source-level regression test).
`freeze_fitted_v21` refuses when either marker exists.

**Provenance.** `capture_provenance` records commit id, branch, tracked-tree dirty flag and
paths, protocol and offsets hashes, all manifest hashes, a content-addressed source-manifest
hash, interpreter and package versions, platform and timestamp. `require_clean_tree` fails
closed on a dirty tracked tree and on any git error. `campaign_preconditions` composes the
full fail-closed preflight and reads no trial data.

**Comparison.** `paired_comparison` computes the L7-minus-physics detection-recall
difference pooled across injected trials with quarter clusters, a percentile interval
(primary, 10,000 resamples, seed 20261024, fixed shared indices) and a BCa interval
(secondary, diagnostic, same draws). It returns `inconclusive` — never equivalence — when
there are fewer than 3 clusters, non-finite replicates, fewer than 2 distinct bootstrap
values, fewer than 3 contributing quarters, an FPR mismatch above 0.02, or two
opposite-signed quarters. With the MMD unset the best available outcome is
`descriptive_only`, and `practical_superiority_claim` is always `false`.
`combine_confirmatory` applies intersection-union across the two noise strata.

**FPR reporting.** `zero_fp_upper_bound` gives the one-sided Clopper–Pearson bound
(0.0387 at n=76, 0.0195 at n=152); `fpr_report` attaches it only at zero false positives and
labels Wilson as trial-level and anti-conservative.

## 3. Tests run

```
cd webapp/backend
.venv/Scripts/python.exe -m pytest tests/test_phase11_v2_stage2.py -q
→ 72 passed in 4.66s
```

All 72 are synthetic-only: fixtures in `tmp_path` or in-memory arrays. The single test that
touches a real file reads `protocol_v2_1.json` read-only and skips when absent. Coverage
groups: protocol hash pin and sidecar, schema/section/invariant rejection (6 parametrised
cases), manifest hash/phase/structure/length, threshold arithmetic (interpolated quantile,
floor binding, floor==quantile, tie-lift at n=30, all-tied scores, saturation, minimum
sample, non-finite handling, 20-seed exceedance property), calibration gates (missing
stratum, test rows, sub-minimum, degenerate, provenance table), markers (round trip, double
begin, double complete, crash evidence, invalid marker, simulated concurrency, no deletion
path), freeze/load (marker refusal, round trip, tamper detection, missing sidecar,
missing provenance), provenance (dirty/clean/git failure/source hash), comparison (MMD
unset, explicit MMD, mismatch, tolerance, heterogeneity, degenerate, too few clusters,
duplicate ids, intersection-union), FPR bounds, and campaign preconditions.

Static checks:

```
ruff check  research/phase11_v2.py tests/test_phase11_v2_stage2.py  → All checks passed
ruff format --check (same two files)                                → already formatted
python -m pytest --collect-only -q                                  → 256 tests collected
```

`--collect-only` imports the modules and executes no test body; 256 = 184 previously
verified + 72 new. The pre-existing 184 tests were **not re-run** in this stage, because the
authorization limited execution to synthetic-only tests and because no tracked file was
modified that could affect them.

## 4. Protected-path evidence

Hashed before and after the test run; all 21 paths byte-identical (0 mismatches):

- nine v1 frozen inputs: `protocol.json` `ded2bd5e…`, `protocol.sha256` `64536dfc…`,
  `offsets.json` `79e8d00e…`, `offsets.sha256` `de8717df…`, `split.json` `5931f5b4…`,
  `windows_primary.json` `6d8eb4b4…`, `windows_sensitivity.json` `b89c6bde…`,
  `null_library.json` `767ff940…`, `experiment_config.json` `43fbddc1…`
- `protocol_v2.json` `7d69d461…`, `protocol_v2.sha256`, `protocol_v2_1.json` `bae1cc58…`,
  `protocol_v2_1.sha256`
- eight files across `smoke/` and `smoke_invalid_scope_20261022/`

`git diff --stat` is empty (no tracked file modified). No `test_generation.json`,
`test_access.json` or `metrics_test.json` exists anywhere under `reports/`.

## 5. Source and runtime provenance

- HEAD: `230c5ae8c26b87abd719c09548a23beab8f37222` (branch `main`, unchanged)
- Tracked tree: clean. Untracked: the two new files above plus the pre-existing Phase 9/10/11
  artifacts and reports; none staged.
- Interpreter: `.venv/Scripts/python.exe`, Python 3.11.17; numpy 2.4.6, pandas 2.3.3,
  scikit-learn 1.9.1, ruff 0.17.0.
- No stage, commit, tag or push was performed.

## 6. Defect found in the frozen protocol text (not fixed — requires a new version)

`protocol_v2_1.json` `thresholds.existence_argument` states that for the interpolated
quantile `e(t0) ≤ (n-1)/n · α < α`, "so the minimum never needs to exceed t0". That sentence
is false for small n. With n = 30 and scores 0…29, q = 27.55 and `e(t0) = 2/30 = 0.0667 > 0.05`,
so the rule must lift to the next observed score; the implemented algorithm does so and
labels it `tie_lift` (covered by `test_tie_lift_when_the_quantile_leaves_too_many_above`).

The operative rules — candidate set including `t0`, minimum candidate within target,
source precedence, and the `e(max) = 0` existence argument — remain correct and complete, so
this is a documentation error only, not a behavioural defect. It is not editable in place:
correcting it requires an authorized v2.2 with a new hash.

## 7. Remaining blockers before any campaign

1. **Stage 2 is not wired to a CLI.** No runner calls these gates yet; the existing
   `run_phase11` still drives the v1 smoke path. Wiring it is a separate, reviewable change.
2. **Pre-campaign audit of the frozen inputs is not re-run.** The audit that produced
   `reports/phase11_pre_campaign_audit.md` predates v2.1 and this module.
3. **Saturation risk is real for L7.** With 42 validation nulls per stratum, a saturating
   score distribution (many ties at 1.0) yields a degenerate threshold; the gate fails
   closed as inconclusive, but that outcome can only be discovered at calibration time.
4. **MMD remains unset (D1)**, so any future confirmatory output is descriptive-only.
5. **Environment pin is unresolved** (venv Python 3.11.17 vs the 3.14.3 stack declared in
   v1). Each run must capture its own versions, which `capture_provenance` now does.
6. **Protocol documentation defect** in §6 above.

## 8. Git status (Phase 11-relevant)

```
?? reports/phase11_generalization/protocol_v2.json
?? reports/phase11_generalization/protocol_v2.sha256
?? reports/phase11_generalization/protocol_v2_1.json
?? reports/phase11_generalization/protocol_v2_1.sha256
?? reports/phase11_generalization/smoke/
?? reports/phase11_generalization/smoke_invalid_scope_20261022/
?? webapp/backend/research/phase11_v2.py
?? webapp/backend/tests/test_phase11_v2_stage2.py
```

Nothing staged. No commit, tag or push.

## 9. Correction to §5 and §7.5 (added during the pre-campaign hardening stage)

The environment claim in this report was wrong. §5 recorded Python 3.11.17 / numpy 2.4.6 /
pandas 2.3.3 as "the virtual environment observed" and §7 item 5 raised that as an
unresolved blocker. That interpreter is the repo-root `.venv`, not the Phase 11 environment.

The authoritative environment is `webapp/backend/.venv`: Python 3.14.3, numpy 2.5.4,
pandas 3.0.6, scipy 1.18.1, scikit-learn 1.9.1, batman-package 2.5.2, pytest 9.1.1. It
matches `requirements-phase11.txt` and protocol v1's declared stack exactly.

Therefore the "environment divergence" finding and unresolved item U3 are withdrawn as a
measurement error on my part, not a project defect. The 72 Stage 2 tests were re-run under
the authoritative interpreter and also pass there.

See `reports/phase11_environment.md` for the resolved policy, and note that the frozen
`environment` block inside `protocol_v2_1.json` / `protocol_v2_2.json` still records the
repo-root versions; correcting that needs a v2.3 protocol and is out of scope.
