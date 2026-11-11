# Phase 11 runner integration design — one-shot enforcement (design only)

Status: design note. **No runner was wired, no execution mode was added, and no campaign
was launched.** This document specifies what a future runner must do so that the one-shot
access state machine is enforced end to end.

## 1. The single authority

`research/test_access.py` is the only implementation of test-access state. Both the legacy
v1 evaluator (`research/phase11.py`) and the v2 preflight/freeze path
(`research/phase11_v2.py`) call it; `phase11_v2` re-exports the marker API rather than
defining its own.

| Operation | Semantics |
|---|---|
| `claim_generation(out_dir, payload)` | Refused if any marker exists. Creates `test_generation.json` in state `started` with `O_CREAT\|O_EXCL`. |
| `claim_access(out_dir, payload)` | Refused if `test_access.json` exists in any state; refused if a generation marker exists but is not `completed`. Creates `test_access.json` in state `started`. |
| `complete_marker(...)` | Only `started -> completed`; atomic replace; nonce re-read; loser fails closed. |
| `marker_state(...)` | `None`, `started`, `completed`, or `invalid` (present but unusable). |
| `assert_no_markers(out_dir)` | Refuses on any marker in any state. |

There is no reset, delete, truncate or "retry" helper, by design.

## 2. Operations that touch test data

A runner may only do these four things with test data, and each needs its own guard:

1. **Generate test trials** (`run_campaign(split_group="test")`) — writes `trials_test.csv`.
2. **Read the generated trials into memory** (pandas load) — a read of sealed rows.
3. **Score the trials** (model inference) — the actual evaluation.
4. **Persist results** (`metrics_test.json`, comparison outputs).

In the current code, (1) is guarded by `claim_generation` + `complete_marker`; (2) and (3)
are inside `evaluate_test`, guarded by `claim_access`. A v2 runner must do the same, and
must not introduce a path that bypasses either claim.

## 3. Required call sequence for a v2 campaign

```
preflight                       # protocol/manifest/offset hashes, clean tree, no markers
  -> fit stage (train+val only) # no test data
  -> freeze fitted artifact     # refuses if any marker exists; writes provenance
  -> claim_generation           # O_EXCL; refusal is terminal
  -> generate trials_test.csv   # the only generation step
  -> complete_marker(generation, {trials_sha256, rows})
  -> claim_access               # requires generation == completed
  -> score + metrics            # the only scoring step
  -> complete_marker(access, results)
```

Invariants the runner must preserve:

- **Claim before touch.** No trial row may be constructed, read or written before the
  corresponding claim exists on disk. Tests in `tests/test_phase11_access_closure.py`
  demonstrate the pattern with spy objects.
- **Claim once.** A second or concurrent attempt is refused; the failure is not retryable
  by software. The report states this explicitly to the operator rather than offering a
  retry flag.
- **Failed attempt is terminal.** If generation or evaluation raises after the claim, the
  marker stays `started`. The runner must not delete it, and must not treat a rerun as
  legitimate. Recovery is a human decision recorded outside the software.
- **Invalid state blocks.** A partial or malformed marker is `invalid`, never absent.
- **Preflight checks markers first.** `campaign_preconditions` already calls
  `assert_no_markers`; a runner must call it before reading any manifest-derived data for
  the test split, not merely before writing.
- **Provenance is captured before the claim**, so a refused attempt still leaves a record
  of the commit, hashes and environment that tried.

## 4. What the runner must not do

- Must not expose `--force`, `--retry`, `--reset` or an equivalent that clears markers.
- Must not fall back to the legacy v1 evaluator when the v2 protocol is configured; the
  legacy evaluator already refuses a schema-2 fitted state, and the v2 CLI pins the v2.2
  protocol hash.
- Must not evaluate from an in-memory trial frame supplied by an operator; trials must
  come from the file whose hash was recorded in the generation marker, and that hash must
  be re-verified at evaluation time.
- Must not treat a `started` marker as resumable.
- Must not claim access when a generation marker exists but is `started`/`invalid`.

## 5. Gaps a future runner must close (not closed here)

1. **Trial-frame provenance.** `evaluate_test` currently accepts a DataFrame from the
   caller. A v2 runner must instead load `trials_test.csv` itself and verify its SHA-256
   against the generation marker before scoring.
2. **Marker-to-artifact binding.** The generation marker records `trials_sha256`; nothing
   yet re-checks it at evaluation time.
3. **Cross-protocol isolation.** v1 output directories and v2 output directories are not
   structurally separated. A runner should use a dedicated v2 output root and refuse to
   reuse a directory that contains any prior artifact.
4. **Audit trail of refusals.** Refusals print to stderr; a runner should also persist a
   refusal record outside the protected tree (never inside it).

## 6. Acceptance criteria before any wiring is approved

- A synthetic end-to-end run that produces a completed generation marker and a completed
  access marker in a temporary directory, then proves every rerun refuses.
- A two-process race test at the runner level (not just the state-machine level).
- Independent review confirming that no code path reaches trial generation or scoring
  without a preceding claim.
