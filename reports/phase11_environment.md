# Phase 11 runtime environment, dependencies, provenance and clean-tree policy

Status: resolved and documented. No package was installed, upgraded or removed, and no
campaign was run. This document supersedes §5 and §7.5 of
`reports/phase11_stage2_hardening.md`, whose environment claim was wrong.

## 1. The environment error this resolves

Two virtual environments exist in the repository:

| Environment | Interpreter | numpy | pandas | scipy | scikit-learn | batman | pytest |
|---|---|---|---|---|---|---|---|
| `webapp/backend/.venv` | **3.14.3** | 2.5.4 | 3.0.6 | 1.18.1 | 1.9.1 | 2.5.2 | 9.1.1 |
| `.venv` (repo root, uv) | 3.11.17 | 2.4.6 | 2.3.3 | 1.17.1 | 1.9.1 | absent | 9.1.1 |

The earlier Stage 2 report recorded only the repo-root environment and concluded that
protocol v1 declared "a stack that is not the virtual environment observed". That conclusion
was wrong: it was based on the wrong interpreter. `webapp/backend/.venv` matches
`requirements-phase11.txt` and protocol v1's declared stack exactly, and is the environment
that produced the historical smoke run.

**Authoritative Phase 11 interpreter: `webapp/backend/.venv/Scripts/python.exe` (Python 3.14.3).**
All Phase 11 test evidence in this stage was produced with it, from the `webapp/backend`
working directory. The repo-root `.venv` must not be used for Phase 11 runs.

## 2. Dependency pins

`webapp/backend/requirements-phase11.txt` is accurate for the authoritative environment and
is left unmodified:

```
numpy==2.5.4
pandas==3.0.6
scipy==1.18.1
scikit-learn==1.9.1
batman-package==2.5.2
pytest==9.1.1          # test-only
```

Its portability caveat stands: wheel availability for other Python versions, platforms or a
fresh machine was not verified, because this work is offline and installing is prohibited.
The pins are a record of one working environment, not a cross-platform lock.

Tooling: `ruff 0.17.0`, installed at `~/.local/bin/ruff`, outside both virtual
environments. It is a linter only and is not a runtime dependency.

## 3. Source provenance

- Baseline commit: `230c5ae8c26b87abd719c09548a23beab8f37222` on `main`, pushed to `origin`.
- The Phase 11 implementation is **untracked** in that commit: `research/phase11_v2.py`,
  `research/run_phase11_v2.py`, `tests/test_phase11_v2_stage2.py`,
  `tests/test_phase11_v2_review.py`, plus the v2/v2.1/v2.2 protocol artifacts.
- Therefore a run cannot be tied to a commit alone. Two mechanisms cover the gap:
  1. `capture_provenance` records HEAD, branch, the dirty flag, and a
     **source-manifest hash** over the enumerated runner files
     (`research/phase11_v2.py`, `research/run_phase11_v2.py` by default, override with
     `--source`).
  2. `fitted.json` persists that whole block, so a later evaluator can re-hash the same
     files and prove whether the source moved.
- A commit that includes the Phase 11 sources is still preferable and is a separate
  authorization.

## 4. Clean-tree policy

- The gate runs `git status --porcelain --untracked-files=no`; a non-empty result aborts
  with `GateError` listing the first dirty paths.
- Untracked files are permitted only if they are enumerated in the run report. This is a
  deliberate choice: the Phase 11 sources themselves are untracked at the baseline commit,
  so a stricter rule would make every run impossible until they are committed.
- A git failure of any kind (missing binary, missing repository) is converted to
  `GateError`, never ignored.
- The dirty flag is persisted even when the gate passes, so a run can never be described as
  clean when it was not.

## 5. Known inconsistency, not fixable within the authorized scope

`protocol_v2_2.json` inherits the `environment` block from v2.1, which records the repo-root
interpreter (Python 3.11.17, numpy 2.4.6, pandas 2.3.3). That block is frozen and this stage
was authorized to correct only `thresholds.existence_argument`. Consequences:

- The block is descriptive only. No rule reads it.
- `capture_provenance` records the **actual** interpreter and package versions of the run,
  which is the authoritative record.
- Correcting the frozen block requires a v2.3 protocol with a new hash; it is not done here.

## 6. Verification commands for any future run

```
cd webapp/backend
.venv/Scripts/python.exe -V                                   # must print 3.14.3
.venv/Scripts/python.exe -m pytest tests/test_phase11_v2_stage2.py tests/test_phase11_v2_review.py -q
.venv/Scripts/python.exe -m research.run_phase11_v2 --mode preflight --out <dir>
```

The CLI always emits JSON on success; it has no `--execute` flag and no campaign mode.
A successful preflight exit code is 0, a CLI refusal is 2, a gate refusal is 3.

## 7. State of this document

No file outside this report was changed by this resolution. The requirements pin file,
both virtual environments, the protocols and all historical artifacts are untouched.

## 8. Status update: v2.3 correction proposal exists

Section 5 said correcting the frozen environment block "requires a v2.3 protocol with a
new hash; it is not done here". A v2.3 artifact now exists as a **proposal**:

| Artifact | SHA-256 | Status |
|---|---|---|
| `reports/phase11_generalization/protocol_v2_3.json` | `e1dc5cc9ed4e6e2dc4645a82efc4f7638fb0f3128248b9810c67ba339f32c154` | proposal only |
| `protocol_v2_3.sha256` | verifies | sidecar |

- It replaces `environment` with the authoritative `webapp/backend/.venv` (Python 3.14.3,
  numpy 2.5.4, pandas 3.0.6, scipy 1.18.1, scikit-learn 1.9.1, batman-package 2.5.2) and
  records the repo-root 3.11.17 environment as not used for Phase 11.
- It binds `immediate_predecessor` to v2.2 (`61f67198…`) and changes nothing outside the
  environment description and provenance metadata; a recursive field comparison enforces
  that at generation time.
- **It is not authorized for execution.** The implementation still pins
  `protocol_v2_2.json`; a regression test asserts that `load_protocol_v21` refuses v2.3.
  Adopting it needs a separate authorization and a code repin.

No frozen artifact was modified by this proposal: v1, v2, v2.1, v2.2 and their sidecars,
and both historical smoke directories, remain byte-identical.
