# Phase 11 — Task 2: Protocol and Execution-Input Freeze Audit

Status: review-only. No campaign, no fitting, no trial generation, no sealed-test
observation, no marker created, no repin, nothing staged or committed. This report is the
only file created.

Authoritative interpreter for every check below:
`webapp/backend/.venv/Scripts/python.exe` (Python 3.14.3).

---

## 1. Protocol decision table

| Version | File | SHA-256 | Schema | False `existence_argument`? | Environment block | Status | Accepted by code |
|---|---|---|---|---|---|---|---|
| v1 | `protocol.json` | `ded2bd5e…75319f` | 1 | n/a | 3.14.3 (correct) | historical | legacy v1 path only |
| v2 | `protocol_v2.json` | `7d69d461…0bc23bec` | 2 | **yes** | 3.11.17 (wrong) | superseded | no |
| v2.1 | `protocol_v2_1.json` | `bae1cc58…4b423e21a80` | 2 | **yes** | 3.11.17 (wrong) | superseded (B1 fix) | no |
| v2.2 | `protocol_v2_2.json` | `61f67198…f124814a` | 2 | no | 3.11.17 (wrong) | **authorized pin** | **yes** |
| v2.3 | `protocol_v2_3.json` | `e1dc5cc9…9f32c154` | 2 | no | 3.14.3 (correct) | **proposal only** | **no** |

Verified acceptance path: `research/phase11_v2.py` pins
`AUTHORIZED_PROTOCOL_NAME = "protocol_v2_2.json"`,
`AUTHORIZED_PROTOCOL_SHA256 = 61f67198…`, `AUTHORIZED_PROTOCOL_VERSION = "phase11b-protocol-v2.2"`.
The loader rejects any other hash or version string, so v2.3 is refused even though its
sidecar is valid.

v2.2 itself declares `campaign_ready: false` and `execution_ready: false`, with
`protocol_fields_open: []`. In other words the authorized protocol says its *content* is
complete but the *system* is not executable until a runner exists.

**Recommendation (for approval, not applied):** adopt v2.3 and repin. Rationale: v2.2
already contains the corrected threshold explanation, but still describes the wrong
interpreter; v2.3 changes **only** the environment description and provenance metadata
(16 paths, none operative). Using v2.3 removes a false provenance statement at zero
scientific cost. The alternative — keep v2.2 and rely on the runtime provenance record —
is defensible because the block is descriptive and `capture_provenance` records the truth,
but it leaves a known-false statement inside the authorized artifact.

---

## 2. Verified hashes, bindings and mismatches

| Artifact | SHA-256 | Sidecar | Verified |
|---|---|---|---|
| `protocol.json` (v1) | `ded2bd5eea3cfb3cbd5af0b67e439a767584b9bf508f02afe2a4b5d56a75319f` | `protocol.sha256` | OK |
| `protocol.sha256` | `64536dfc3d23b92cfffed95eccbebb0227af79e616460385a54bf954192f385e` | — | — |
| `offsets.json` | `79e8d00eeef88c4e05cb571a64cc871dd5549d1c5e7ef5fd11d32021741b5be6` | `offsets.sha256` | OK |
| `offsets.sha256` | `de8717df4250817a25b7d5ec217cb072b93e7a5dae2953afbf4584ff1b6124b9` | — | — |
| `split.json` | `5931f5b4fc7450bb0212391f970748e7c4171c76c27697e85a5507bcfad718c1` | none | bound in protocols |
| `windows_primary.json` | `6d8eb4b4efad96ab5a78fab1c396e0367b0801aecd23fb3f07f3347f08d9f599` | none | bound in protocols |
| `windows_sensitivity.json` | `b89c6bded0c0b22a446771c9a572d0dafb91fb5ce546d4558ad492b68e7fe060` | none | bound in protocols |
| `null_library.json` | `767ff9408c70a9c918ae5de69b0608f16dd461b461ef516cba0ccadc892ad8b8` | none | bound in protocols |
| `experiment_config.json` | `43fbddc15c74c6262db9b56652ed393aca0ea4849d6b2f2df072d28079e7b4ce` | none | bound in protocols |
| `protocol_v2.json` | `7d69d461f036d7430be373b1010821a1e420523abc1bdee6b71996ee0bc23bec` | `protocol_v2.sha256` | OK |
| `protocol_v2_1.json` | `bae1cc583e6dc85f5190c430ed55de8d2799bf994cac03d40ce7a3b423e21a80` | `protocol_v2_1.sha256` | OK |
| `protocol_v2_2.json` | `61f671986814b2b6d1f02d1d8da1e31e613ddc24ef1e545e54f68666f124814a` | `protocol_v2_2.sha256` | OK |
| `protocol_v2_3.json` | `e1dc5cc9ed4e6e2dc4645a82efc4f7638fb0f3128248b9810c67ba339f32c154` | `protocol_v2_3.sha256` | OK |

Binding chains, all verified against the actual bytes:

- v1 `manifests` block → all 5 manifests **MATCH**.
- v2 / v2.1 / v2.2 / v2.3 `frozen_inputs.files` → 9 entries each (7 JSON + both sidecars),
  **no mismatches, nothing missing**.
- `supersedes` in every v2.x → v1 `ded2bd5e…` **OK**.
- `immediate_predecessor`: v2.1→v2 `7d69d461…` OK, v2.2→v2.1 `bae1cc58…` OK,
  v2.3→v2.2 `61f67198…` OK.

**Sidecar coverage gap (not a defect, but a single point of trust):** only
`protocol(.json)` and `offsets.json` have sidecars among the seven inputs. The five
manifests are bound *only* by the hash lists inside the protocol artifacts. A corrupt or
replaced manifest is therefore detectable through the protocol but not through a
standalone sidecar. Recommend, for a future freeze, sidecars for all seven (a new
protocol version would be required to bind them; not done here).

**Ambiguities checked:** v2.2 cannot bind its own sidecar (self-reference); no artifact
binds v2.3 (correct, it is a proposal). No missing artifact and no inconsistent hash was
found. All values above agree with `reports/phase11_pre_campaign_audit.md` §13.5 and with
the `frozen_inputs` blocks recorded earlier.

---

## 3. Environment and reproducibility

| Component | Version (authoritative venv) | `requirements-phase11.txt` | Match |
|---|---|---|---|
| Python | 3.14.3 | declared in header | yes |
| NumPy | 2.5.4 | 2.5.4 | yes |
| pandas | 3.0.6 | 3.0.6 | yes |
| SciPy | 1.18.1 | 1.18.1 | yes |
| scikit-learn | 1.9.1 | 1.9.1 | yes |
| batman-package | 2.5.2 | 2.5.2 | yes |
| pytest | 9.1.1 | 9.1.1 | yes |

Consistency with code assumptions: `research/phase11_v2.py` imports `numpy`, `pandas`,
`scikit`, `scipy.stats.norm`; `research/phase11.py` imports `sklearn` and `pickle`; all
resolve in this interpreter. No import failed during the read-only checks.

**Discrepancy D1:** the authorized v2.2 `environment.observed_venv_interpreter` records
Python 3.11.17 / NumPy 2.4.6 / pandas 2.3.3 (the repository-root `.venv`), and its
`divergence` text asserts the 3.14 stack is absent. That is false: `webapp/backend/.venv`
is 3.14.3 and matches the pin file exactly. v2.3 corrects this; v2.2 cannot be edited.

The repository-root `.venv` (3.11.17) exists and must not be used for Phase 11 runs.

---

## 4. Split and threshold audit (static, manifest metadata only)

| Check | Result |
|---|---|
| Unit of independence | Kepler quarter (`split.unit_of_independence`) |
| Quotas vs assignment | 7 train / 3 val / 5 test == assignment counts, 15 quarters |
| Test quarters | `Q02, Q09, Q13, Q14, Q17` |
| Every 5-day window's split equals its quarter's assignment | 207/207 consistent |
| Every 3-day window's split equals its quarter's assignment | 345/345 consistent |
| Quarters shared across splits | none, in either manifest |
| Calibration pools | detector = train+val nulls per stratum (134/stratum); L7 = validation nulls only (42/stratum) |
| Code enforces no test rows in calibration | yes: `phase11_v2.py:372,379` refuse test rows |
| Minimum calibration n | 30 per stratum; L7 42 ≥ 30, detector 134 ≥ 30 |
| Minimum test-side data | 3 clusters, 30 nulls/stratum, 20 injections per depth per stratum |
| Derived test denominators | 152 nulls (76/stratum); 720 injections (360/stratum; 72/depth/stratum) — agree with protocol |
| FPR definition | k/n per stratum, primary interval = one-sided Clopper–Pearson at zero FP (0.0387 at n=76; 0.0195 at n=152) |
| Secondary FPR interval | Wilson, labelled trial-level and anti-conservative |
| Cluster interval | percentile primary, BCa diagnostic, 10,000 resamples, seed 20261024, unit = quarter |
| Comparison gate | FPR mismatch > 0.02 ⇒ stratum inconclusive |
| Heterogeneity guard | ≥2 of 5 quarters opposite sign ⇒ inconclusive |
| Inconclusive gates | <3 clusters, <2 distinct bootstrap values, <3 contributing quarters, non-finite replicates |
| MMD | `null`; caller-supplied overrides refused (`phase11_v2.py:834`); practical-superiority flag hard-wired false |
| Timing tolerance | 0.0377 d, recovery boundary `<= 0.0377`, code `core.TOLERANCE_DAYS` |
| Seeds | split 20261022, offsets 20261023, model 20261025, bootstrap 20261024 — match code constants |

Additional findings:

- **D2 — protocol-to-code gap.** The v2 module implements thresholds, comparison, markers,
  preflight and provenance, but contains **no fitting or evaluation path**
  (`fit_models`, `evaluate_test`, `run_campaign` all absent). `execution_ready: false` in
  v2.2/v2.3 is therefore accurate. Fitting remains a v1 function whose L7 calibration
  (validation nulls only) matches the v2.2 rule.
- **D3 — latent calibration API.** `calibrate_thresholds_v21` is implemented and tested but
  has no caller outside tests.
- **D4 — coarse L7 operating point.** 42 calibration nulls per stratum: the rule quantises
  the threshold to steps of 0.0238 and realised exceedance can only be 0, 0.0238 or 0.0476.
  Documented in the protocol; must be stated wherever an operating point is reported.
- **D5 — low-resolution FPR gate.** The 0.02 mismatch gate is evaluated on 76 nulls per
  stratum, so it detects only large operating-point differences. Passing it is not proof
  of matched FPRs.
- **D6 — tolerance rounding.** 0.0377 vs exact half-duration 0.0377365 (≈3.2 s). Frozen and
  documented; not changed.
- **D7 — sidecar coverage** (see §2).
- **D8 — untracked sources.** The Phase 11 implementation is untracked at HEAD
  `230c5ae8…`, so provenance rests on the source-manifest hash, not a commit id.

No discrepancy between the protocol's operative numbers and the manifests was found.

---

## 5. Future-run provenance contract

A runner may not be authorized until it captures, before any sealed-test operation:

1. **Repository state** — commit id, branch, and tracked-tree dirty flag (clean required).
2. **Protocol** — path, version, SHA-256, and sidecar verification.
3. **Every frozen input** — `offsets.json`, `split.json`, `windows_primary.json`,
   `windows_sensitivity.json`, `null_library.json`, `experiment_config.json`, plus sidecars
   where they exist.
4. **Source manifest hash** — content hash over the enumerated runner modules.
5. **Environment** — interpreter path, Python version, NumPy/pandas/SciPy/scikit-learn/
   batman-package versions, platform, read from the running process (not from a file).
6. **Fitted model hash** — `model.pkl` SHA-256 recorded inside `fitted.json`, and the
   `fitted.json` sidecar.
7. **Calibration artifact** — per-stratum threshold records (value, source label, n,
   calibration exceedance, floor binding, degeneracy flag).
8. **Generated test-trial file hash** — `trials_test.csv` SHA-256 written into the
   generation marker at completion.
9. **Marker linkage** — generation marker (`started`→`completed`, carrying the trial hash)
   and access marker (`started`→`completed`, carrying protocol and fitted hashes).
10. **Result artifacts** — hashes of `metrics_test.json` and any comparison output.

Two mandatory runtime verifications:

- **Before evaluation**, the runner must recompute the SHA-256 of the generated trial file
  and compare it with the hash in the completed generation marker; a mismatch is fatal.
- **Before any sealed-test read or regeneration**, the runner must acquire the access claim
  and verify that no marker exists in any state. Claims are exclusive across processes,
  are never reset by software, and a failed attempt is terminal.

This is a contract only; nothing here is wired.

---

## 6. Unresolved issues and recommendations

| # | Issue | Recommendation |
|---|---|---|
| 1 | Authorized v2.2 carries a false environment statement | Adopt v2.3 (environment-only change) with a repin — **requires your explicit approval; not done** |
| 2 | `execution_ready: false` in both v2.2 and v2.3 | Flip only after a runner exists and passes independent synthetic testing |
| 3 | v2 has no fitting/evaluation path | Implement outside this task, behind the access state machine |
| 4 | Five manifests lack sidecars | Add sidecars in a future protocol version |
| 5 | L7 42-null quantisation; 76-null FPR gate | Report both limitations wherever operating points appear |
| 6 | Sources untracked at HEAD | Commit the Phase 11 sources (separate authorization) |
| 7 | MMD unset | Remains your decision; until set, all outcomes are descriptive-only |

No protocol was selected automatically and no repin occurred.

---

## 7. Exact commands run and results

All commands were read-only; the interpreter was `webapp/backend/.venv/Scripts/python.exe`.

| Command (purpose) | Result |
|---|---|
| `sha256sum` over the 17 artifacts in `reports/phase11_generalization` | hashes recorded in §2 |
| `sha256sum -c` for the six sidecars | all six `OK` |
| Python: verify v1 `manifests` and each v2.x `frozen_inputs.files` against file bytes | 5/5 and 9/9 per protocol, no mismatch |
| Python: verify `supersedes` and `immediate_predecessor` hashes | all OK |
| Python: print per-version `existence_argument` flag and environment python | v2, v2.1 false clause; v2.2, v2.3 clean |
| Python: interpreter and package versions; compare with `requirements-phase11.txt` | 3.14.3 stack; 6/6 pins match |
| Python: window counts, per-quarter split consistency, quotas | 207 and 345 windows; 0 mismatches; quotas match |
| Python: recursive v2.2→v2.3 diff | 16 paths, all environment/provenance |
| `find reports -name trials_test.csv -o -name test_access.json -o -name test_generation.json -o -name metrics_test.json` | no matches |
| `git status -sb`, `git diff --stat`, `git diff --cached --name-only`, `git diff --check` | see §8 |

No test suite was executed in this task: the audit is static, and running tests was not
needed to establish any claim above.

---

## 8. Preservation and Git evidence

- **21/21 protected artifacts byte-identical** to the pre-Stage-2 snapshot: the nine v1
  inputs, the v2/v2.1 pairs, and the eight files in the two historical smoke directories.
- Six sidecars verify; v2.2 `61f67198…` and v2.3 `e1dc5cc9…` unchanged.
- No `test_generation.json`, `test_access.json`, `trials_test.csv` or `metrics_test.json`
  exists anywhere under `reports/`.
- `git status`: branch `main`, **0 staged**, `git diff --check` clean, HEAD `230c5ae8…`.
  Tracked modifications remain the three files from earlier hardening stages
  (`generalization.py`, `phase11.py`, `run_phase11.py`); this task changed none of them.
- The only file created by this task is this report.

**Stop for review.** No protocol was adopted, no runner was wired, no campaign was
launched, and no sealed-test observation was read or generated.
